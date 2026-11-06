from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMembership, User


class OrganizationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_user_by_firebase_uid(self, firebase_uid: str) -> User | None:
        return self.session.scalar(select(User).where(User.firebase_uid == firebase_uid))

    def get_membership(self, organization_id: UUID, user_id: UUID) -> OrganizationMembership | None:
        return self.session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )

    def list_for_user(self, user_id: UUID) -> list[OrganizationMembership]:
        statement = (
            select(OrganizationMembership)
            .where(OrganizationMembership.user_id == user_id)
            .order_by(OrganizationMembership.created_at.asc())
        )
        return list(self.session.scalars(statement).all())

    def get_organization(self, organization_id: UUID) -> Organization | None:
        return self.session.get(Organization, organization_id)

    def create_organization(self, organization: Organization, membership: OrganizationMembership) -> None:
        self.session.add_all([organization, membership])
