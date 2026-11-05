from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repositories.auth_repository import AuthRepository
from app.schemas.v1.auth import (
    AuthenticatedUserResponse,
    OrganizationMembershipSummary,
)


class AuthIdentityService:
    """Resolve a verified Firebase identity to its SaviraCortex account."""

    def __init__(self, session: Session) -> None:
        self.repository = AuthRepository(session)

    def get_current_user(self, firebase_claims: dict) -> AuthenticatedUserResponse:
        firebase_uid = firebase_claims.get("uid")
        if not isinstance(firebase_uid, str) or not firebase_uid.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The verified Firebase identity is missing a UID.",
            )

        user = self.repository.get_user_by_firebase_uid(firebase_uid)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This Firebase account is authenticated but not registered in SaviraCortex. Complete organization signup first.",
            )

        memberships = self.repository.get_memberships_for_user(user.id)
        firebase_metadata = firebase_claims.get("firebase")
        sign_in_provider = (
            firebase_metadata.get("sign_in_provider")
            if isinstance(firebase_metadata, dict)
            else None
        )

        return AuthenticatedUserResponse(
            user_id=str(user.id),
            firebase_uid=user.firebase_uid,
            email=user.email,
            phone_number=user.phone_number,
            display_name=user.display_name,
            sign_in_provider=sign_in_provider,
            organizations=[
                OrganizationMembershipSummary(
                    organization_id=str(membership.organization_id),
                    organization_name=membership.organization.name,
                    role=membership.role,
                )
                for membership in memberships
            ],
        )
