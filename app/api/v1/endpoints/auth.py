from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.schemas.v1.auth import OrganizationSignupRequest, OrganizationSignupResponse
from app.services.auth.signup_service import OrganizationSignupService

router = APIRouter(prefix="/auth", tags=["Authentication"])


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
    return OrganizationSignupService(session).signup(payload, firebase_claims)
