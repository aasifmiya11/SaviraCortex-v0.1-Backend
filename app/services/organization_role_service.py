from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import OrganizationRole
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.organization_role_repository import OrganizationRoleRepository
from app.schemas.v1.organization_roles import OrganizationRoleCreateRequest, OrganizationRoleResponse


class OrganizationRoleService:
    """Manage custom role definitions within the caller's organization."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.organizations = OrganizationRepository(session)
        self.roles = OrganizationRoleRepository(session)

    def _membership(self, organization_id: UUID, claims: dict):
        uid = claims.get("uid")
        if not isinstance(uid, str) or not uid.strip():
            raise HTTPException(status_code=401, detail="The verified Firebase identity is missing a UID.")
        user = self.organizations.get_user_by_firebase_uid(uid)
        if user is None:
            raise HTTPException(status_code=404, detail="This Firebase account is not registered in SaviraCortex.")
        membership = self.organizations.get_membership(organization_id, user.id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Organization not found or you are not a member of it.")
        return membership

    def list_roles(self, organization_id: UUID, claims: dict) -> list[OrganizationRoleResponse]:
        membership = self._membership(organization_id, claims)
        if membership.role not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Only organization owners and admins can view role management.")
        return [
            OrganizationRoleResponse.model_validate(role)
            for role in self.roles.list_for_organization(organization_id)
        ]

    def create_role(
        self, organization_id: UUID, payload: OrganizationRoleCreateRequest, claims: dict
    ) -> OrganizationRoleResponse:
        membership = self._membership(organization_id, claims)
        if membership.role not in {"owner", "admin"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization owners and admins can create custom roles.",
            )
        role = OrganizationRole(
            id=uuid4(),
            organization_id=organization_id,
            name=payload.name,
            description=payload.description,
        )
        try:
            self.roles.create(role)
            self.session.commit()
            self.session.refresh(role)
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A role with this name already exists in this organization.",
            ) from exc
        except Exception:
            self.session.rollback()
            raise
        return OrganizationRoleResponse.model_validate(role)
