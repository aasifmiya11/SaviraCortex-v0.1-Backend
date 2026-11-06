from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OrganizationRole


class OrganizationRoleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_organization(self, organization_id: UUID) -> list[OrganizationRole]:
        statement = (
            select(OrganizationRole)
            .where(OrganizationRole.organization_id == organization_id)
            .order_by(OrganizationRole.name.asc())
        )
        return list(self.session.scalars(statement).all())

    def create(self, role: OrganizationRole) -> None:
        self.session.add(role)
