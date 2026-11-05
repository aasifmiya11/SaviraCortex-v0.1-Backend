from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.schemas.v1.auth import (
    AuthenticatedUserResponse,
    OrganizationSignupRequest,
    OrganizationSignupResponse,
)
from app.services.auth.identity_service import AuthIdentityService
from app.services.auth.signup_service import OrganizationSignupService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get(
    "/me",
    response_model=AuthenticatedUserResponse,
    summary="Get the authenticated SaviraCortex user and organization memberships",
)
def get_current_user(
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
) -> AuthenticatedUserResponse:
    """Works with Firebase ID tokens from Email/Password, Phone, or Google."""
    return AuthIdentityService(session).get_current_user(firebase_claims)


@router.post(
    "/organizations/signup",
    response_model=OrganizationSignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an organization and its initial administrator",
)
def organization_signup(
    payload: OrganizationSignupRequest,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
) -> OrganizationSignupResponse:
    """Accepts a verified Firebase email identity or a verified phone identity."""
    return OrganizationSignupService(session).signup(payload, firebase_claims)
