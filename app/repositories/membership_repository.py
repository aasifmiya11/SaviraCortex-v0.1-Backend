from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    OrganizationDepartment,
    OrganizationDepartmentMembership,
    OrganizationMembership,
    OrganizationRole,
    UserRoleAssignment,
    User,
)


class MembershipRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_user_by_firebase_uid(self, uid: str) -> User | None:
        return self.session.scalar(select(User).where(User.firebase_uid == uid))

    def get_user(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_membership(self, organization_id: UUID, user_id: UUID) -> OrganizationMembership | None:
        return self.session.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        ))

    def list_members(self, organization_id: UUID):
        statement = (
            select(
                OrganizationMembership,
                User.email,
                User.display_name,
                OrganizationRole.name,
            )
            .join(User, User.id == OrganizationMembership.user_id)
            .outerjoin(
                UserRoleAssignment,
                (UserRoleAssignment.organization_id == OrganizationMembership.organization_id)
                & (UserRoleAssignment.user_id == OrganizationMembership.user_id),
            )
            .outerjoin(
                OrganizationRole,
                (OrganizationRole.organization_id == UserRoleAssignment.organization_id)
                & (OrganizationRole.id == UserRoleAssignment.role_id),
            )
            .where(OrganizationMembership.organization_id == organization_id)
            .order_by(User.display_name, User.email, OrganizationRole.name)
        )
        rows = self.session.execute(statement).all()
        grouped = {}
        for membership, email, display_name, role_name in rows:
            item = grouped.setdefault(
                membership.user_id,
                [membership, email, display_name, []],
            )
            if role_name and role_name not in item[3]:
                item[3].append(role_name)
        return [
            (membership, email, display_name, sorted(custom_roles))
            for membership, email, display_name, custom_roles in grouped.values()
        ]

    def add_membership(self, membership: OrganizationMembership) -> None:
        self.session.add(membership)

    def list_department_members(self, organization_id: UUID, department_id: UUID):
        statement = (
            select(OrganizationDepartmentMembership, User.email, User.display_name)
            .join(User, User.id == OrganizationDepartmentMembership.user_id)
            .where(
                OrganizationDepartmentMembership.organization_id == organization_id,
                OrganizationDepartmentMembership.department_id == department_id,
            )
            .order_by(User.display_name, User.email)
        )
        return list(self.session.execute(statement).all())

    def get_department(self, organization_id: UUID, department_id: UUID) -> OrganizationDepartment | None:
        return self.session.scalar(select(OrganizationDepartment).where(
            OrganizationDepartment.organization_id == organization_id,
            OrganizationDepartment.id == department_id,
        ))

    def get_department_assignment(self, organization_id: UUID, department_id: UUID, user_id: UUID):
        return self.session.get(OrganizationDepartmentMembership, (organization_id, user_id, department_id))

    def add_department_assignment(self, assignment: OrganizationDepartmentMembership) -> None:
        self.session.add(assignment)

    def delete(self, record) -> None:
        self.session.delete(record)