from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMembership, User


class AuthRepository:
    """Persistence operations for organization signup."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_user_by_firebase_uid(self, firebase_uid: str) -> User | None:
        return self.session.scalar(
            select(User).where(User.firebase_uid == firebase_uid)
        )

    def get_user_by_email(self, normalized_email: str) -> User | None:
        return self.session.scalar(
            select(User).where(User.email == normalized_email)
        )

    def create_signup_records(
        self,
        *,
        user: User,
        organization: Organization,
        membership: OrganizationMembership,
    ) -> None:
        self.session.add_all([user, organization, membership])
