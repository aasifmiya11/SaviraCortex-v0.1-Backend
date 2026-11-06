from uuid import UUID, uuid4

from sqlalchemy import select
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    OrganizationDepartmentMembership,
    OrganizationMembership,
    OrganizationRole,
    UserRoleAssignment,
)
from app.repositories.membership_repository import MembershipRepository
from app.schemas.v1.department_memberships import DepartmentMembershipResponse
from app.schemas.v1.memberships import OrganizationMembershipResponse
from app.schemas.v1.organization_roles import OrganizationRoleResponse


class MembershipService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = MembershipRepository(session)

    def _actor_membership(self, organization_id: UUID, claims: dict) -> OrganizationMembership:
        uid = claims.get("uid")
        if not isinstance(uid, str) or not uid.strip():
            raise HTTPException(status_code=401, detail="The verified Firebase identity is missing a UID.")
        user = self.repository.get_user_by_firebase_uid(uid)
        if user is None:
            raise HTTPException(status_code=404, detail="This Firebase account is not registered in SaviraCortex.")
        membership = self.repository.get_membership(organization_id, user.id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Organization not found or you are not a member of it.")
        return membership

    def _require_manager(self, organization_id: UUID, claims: dict) -> OrganizationMembership:
        actor = self._actor_membership(organization_id, claims)
        if actor.role not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Only organization owners and admins can manage memberships.")
        return actor

    @staticmethod
    def _membership_response(row, email, display_name, custom_roles=None) -> OrganizationMembershipResponse:
        return OrganizationMembershipResponse(
            user_id=row.user_id, organization_id=row.organization_id, role=row.role,
            created_at=row.created_at, email=email, display_name=display_name,
            custom_roles=custom_roles or [],
        )

    @staticmethod
    def _department_response(row, email, display_name) -> DepartmentMembershipResponse:
        return DepartmentMembershipResponse(
            organization_id=row.organization_id, user_id=row.user_id,
            department_id=row.department_id, created_at=row.created_at,
            email=email, display_name=display_name,
        )

    def list_members(self, organization_id: UUID, claims: dict) -> list[OrganizationMembershipResponse]:
        self._actor_membership(organization_id, claims)
        return [self._membership_response(*item) for item in self.repository.list_members(organization_id)]

    def add_member(self, organization_id: UUID, user_id: UUID, role: str, claims: dict) -> OrganizationMembershipResponse:
        actor = self._require_manager(organization_id, claims)
        if role == "admin" and actor.role != "owner":
            raise HTTPException(status_code=403, detail="Only an organization owner can grant the admin role.")
        user = self.repository.get_user(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found in SaviraCortex.")
        if self.repository.get_membership(organization_id, user_id):
            raise HTTPException(status_code=409, detail="This user is already a member of the organization.")
        membership = OrganizationMembership(id=uuid4(), organization_id=organization_id, user_id=user_id, role=role)
        try:
            self.repository.add_membership(membership)
            self.session.commit()
            self.session.refresh(membership)
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(status_code=409, detail="This user is already a member of the organization.") from exc
        except Exception:
            self.session.rollback()
            raise
        return self._membership_response(membership, user.email, user.display_name)

    def assign_custom_roles(
        self, organization_id: UUID, user_id: UUID, role_ids: list[UUID], claims: dict
    ) -> list[OrganizationRoleResponse]:
        """Add one or more organization-defined roles to an existing member."""
        self._require_manager(organization_id, claims)
        membership = self.repository.get_membership(organization_id, user_id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Organization membership not found.")

        roles = list(self.session.scalars(
            select(OrganizationRole).where(
                OrganizationRole.organization_id == organization_id,
                OrganizationRole.id.in_(role_ids),
            )
        ).all())
        if len(roles) != len(role_ids):
            raise HTTPException(
                status_code=404,
                detail="One or more role IDs do not belong to this organization.",
            )

        existing_ids = set(self.session.scalars(
            select(UserRoleAssignment.role_id).where(
                UserRoleAssignment.organization_id == organization_id,
                UserRoleAssignment.user_id == user_id,
                UserRoleAssignment.role_id.in_(role_ids),
            )
        ).all())
        try:
            for role in roles:
                if role.id not in existing_ids:
                    self.session.add(UserRoleAssignment(
                        id=uuid4(),
                        organization_id=organization_id,
                        user_id=user_id,
                        role_id=role.id,
                    ))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return [
            OrganizationRoleResponse.model_validate(role)
            for role in sorted(roles, key=lambda item: item.name.casefold())
        ]

    def update_member(self, organization_id: UUID, user_id: UUID, role: str, claims: dict) -> OrganizationMembershipResponse:
        actor = self._require_manager(organization_id, claims)
        target = self.repository.get_membership(organization_id, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Organization membership not found.")
        if target.role == "owner":
            raise HTTPException(status_code=409, detail="Owner membership cannot be changed through this endpoint.")
        if actor.role != "owner":
            raise HTTPException(status_code=403, detail="Only an organization owner can change membership roles.")
        user = self.repository.get_user(user_id)
        target.role = role
        try:
            self.session.commit()
            self.session.refresh(target)
        except Exception:
            self.session.rollback()
            raise
        return self._membership_response(target, user.email if user else None, user.display_name if user else None)

    def remove_member(self, organization_id: UUID, user_id: UUID, claims: dict) -> None:
        actor = self._require_manager(organization_id, claims)
        target = self.repository.get_membership(organization_id, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Organization membership not found.")
        if target.role == "owner":
            raise HTTPException(status_code=409, detail="Owner membership cannot be removed through this endpoint.")
        if actor.role != "owner" and target.role != "member":
            raise HTTPException(status_code=403, detail="Admins can remove members, but only owners can remove admins.")
        try:
            self.repository.delete(target)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def list_department_members(self, organization_id: UUID, department_id: UUID, claims: dict) -> list[DepartmentMembershipResponse]:
        self._actor_membership(organization_id, claims)
        if self.repository.get_department(organization_id, department_id) is None:
            raise HTTPException(status_code=404, detail="Department not found in this organization.")
        return [self._department_response(*item) for item in self.repository.list_department_members(organization_id, department_id)]

    def assign_department(self, organization_id: UUID, department_id: UUID, user_id: UUID, claims: dict) -> DepartmentMembershipResponse:
        self._require_manager(organization_id, claims)
        if self.repository.get_department(organization_id, department_id) is None:
            raise HTTPException(status_code=404, detail="Department not found in this organization.")
        membership = self.repository.get_membership(organization_id, user_id)
        if membership is None:
            raise HTTPException(status_code=404, detail="The user is not a member of this organization.")
        if self.repository.get_department_assignment(organization_id, department_id, user_id):
            raise HTTPException(status_code=409, detail="This user is already assigned to the department.")
        assignment = OrganizationDepartmentMembership(
            organization_id=organization_id, user_id=user_id, department_id=department_id,
        )
        try:
            self.repository.add_department_assignment(assignment)
            self.session.commit()
            self.session.refresh(assignment)
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(status_code=409, detail="This user is already assigned to the department.") from exc
        except Exception:
            self.session.rollback()
            raise
        user = self.repository.get_user(user_id)
        return self._department_response(assignment, user.email if user else None, user.display_name if user else None)

    def unassign_department(self, organization_id: UUID, department_id: UUID, user_id: UUID, claims: dict) -> None:
        self._require_manager(organization_id, claims)
        assignment = self.repository.get_department_assignment(organization_id, department_id, user_id)
        if assignment is None:
            raise HTTPException(status_code=404, detail="Department membership not found.")
        try:
            self.repository.delete(assignment)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise