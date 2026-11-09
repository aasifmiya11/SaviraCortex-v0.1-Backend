from datetime import datetime, timezone
import logging
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Organization,
    OrganizationDepartment,
    OrganizationMembership,
    OrganizationRole,
    User,
)
from app.repositories.auth_repository import AuthRepository
from app.schemas.v1.auth import OrganizationSignupRequest, OrganizationSignupResponse

logger = logging.getLogger(__name__)


def _integrity_error_detail(exc: IntegrityError) -> str:
    original = getattr(exc, "orig", None)
    diagnostic = getattr(original, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    messages = {
        "users_firebase_uid_key": "This sign-in identity is already registered. Please sign in instead.",
        "users_email_key": "An account with this email address already exists. Please sign in instead.",
        "uq_organization_department_name": "A department with that name already exists in this organization.",
        "uq_organization_role_name": "A role with that name already exists in this organization.",
        "uq_organization_membership": "This user is already a member of the organization.",
    }
    return messages.get(
        constraint,
        "Organization setup could not be saved because a database uniqueness or relationship constraint was violated. Check the submitted account details and database migration.",
    )


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
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The verified Firebase identity is missing a UID.")

        normalized_email = email.strip().lower() if isinstance(email, str) and email.strip() else None
        normalized_phone = phone_number.strip() if isinstance(phone_number, str) and phone_number.strip() else None

        if not email_verified and not normalized_phone:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verify your email or sign in with a verified phone number before organization signup.")
        if not normalized_email and not normalized_phone:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A verified email address or phone number is required.")
        if self.repository.get_user_by_firebase_uid(firebase_uid):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This Firebase account is already registered.")
        if normalized_email and self.repository.get_user_by_email(normalized_email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email address already exists.")

        user = User(id=uuid4(), firebase_uid=firebase_uid, email=normalized_email, phone_number=normalized_phone, display_name=payload.admin_name)
        organization = Organization(id=uuid4(), name=payload.organization_name, onboarding_completed_at=datetime.now(timezone.utc))
        membership = OrganizationMembership(id=uuid4(), organization_id=organization.id, user_id=user.id, role="owner")
        departments = [
            OrganizationDepartment(id=uuid4(), organization_id=organization.id, name=item.name, description=item.description, created_by=user.id)
            for item in payload.departments
        ]
        roles = [
            OrganizationRole(id=uuid4(), organization_id=organization.id, name=item.name, description=item.description)
            for item in payload.roles
        ]

        try:
            # Persist the tenant and owner first within the same transaction.
            # Dependent rows must never be flushed before organizations exists.
            self.session.add_all([user, organization])
            self.session.flush()

            self.session.add_all([membership, *departments, *roles])
            self.session.commit()
        except IntegrityError as exc:
            original = getattr(exc, "orig", None)
            diagnostic = getattr(original, "diag", None)
            constraint = getattr(diagnostic, "constraint_name", None)
            sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
            logger.exception(
                "Organization signup transaction failed: constraint=%s sqlstate=%s db_error=%s",
                constraint,
                sqlstate,
                str(original) if original is not None else str(exc),
            )
            self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_integrity_error_detail(exc),
            ) from exc
        except Exception:
            self.session.rollback()
            raise

        return OrganizationSignupResponse(message="Organization registered successfully.", user_id=str(user.id), organization_id=str(organization.id), role=membership.role)
