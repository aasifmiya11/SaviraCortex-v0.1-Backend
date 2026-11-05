from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMembership, User
from app.repositories.auth_repository import AuthRepository
from app.schemas.v1.auth import OrganizationSignupRequest, OrganizationSignupResponse


class OrganizationSignupService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AuthRepository(session)

    def signup(
        self,
        payload: OrganizationSignupRequest,
        firebase_claims: dict,
    ) -> OrganizationSignupResponse:
        firebase_uid = firebase_claims.get("uid")
        email = firebase_claims.get("email")
        phone_number = firebase_claims.get("phone_number")
        email_verified = firebase_claims.get("email_verified") is True

        if not isinstance(firebase_uid, str) or not firebase_uid.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The verified Firebase identity is missing a UID.",
            )

        normalized_email = (
            email.strip().lower()
            if isinstance(email, str) and email.strip()
            else None
        )
        normalized_phone = (
            phone_number.strip()
            if isinstance(phone_number, str) and phone_number.strip()
            else None
        )

        # Firebase verifies phone ownership before issuing a phone-auth ID token.
        # Email-based providers must supply a verified email claim.
        if not email_verified and not normalized_phone:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Verify your email or sign in with a verified phone number before organization signup.",
            )
        if not normalized_email and not normalized_phone:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A verified email address or phone number is required.",
            )

        if self.repository.get_user_by_firebase_uid(firebase_uid):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Firebase account is already registered.",
            )
        if normalized_email and self.repository.get_user_by_email(normalized_email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email address already exists.",
            )

        user = User(
            id=uuid4(),
            firebase_uid=firebase_uid,
            email=normalized_email,
            phone_number=normalized_phone,
            display_name=payload.admin_name,
        )
        organization = Organization(
            id=uuid4(),
            name=payload.organization_name,
        )
        membership = OrganizationMembership(
            id=uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role="admin",
        )

        try:
            self.repository.create_signup_records(
                user=user,
                organization=organization,
                membership=membership,
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The account or organization signup conflicts with existing data.",
            ) from exc
        except Exception:
            self.session.rollback()
            raise

        return OrganizationSignupResponse(
            message="Organization registered successfully.",
            user_id=str(user.id),
            organization_id=str(organization.id),
            role=membership.role,
        )
