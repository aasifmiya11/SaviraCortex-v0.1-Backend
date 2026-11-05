from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OrganizationDepartment, OrganizationMembership, User


class DepartmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_user_by_firebase_uid(self, firebase_uid: str) -> User | None:
        return self.session.scalar(select(User).where(User.firebase_uid == firebase_uid))

    def get_membership(self, organization_id: UUID, user_id: UUID) -> OrganizationMembership | None:
        return self.session.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        ))

    def list_departments(self, organization_id: UUID) -> list[OrganizationDepartment]:
        statement = select(OrganizationDepartment).where(
            OrganizationDepartment.organization_id == organization_id
        ).order_by(OrganizationDepartment.name.asc())
        return list(self.session.scalars(statement).all())

    def create_department(self, department: OrganizationDepartment) -> None:
        self.session.add(department)
