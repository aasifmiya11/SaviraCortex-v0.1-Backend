from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.schemas.v1.organizations import (
    OrganizationCreateRequest,
    OrganizationListItem,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED, summary="Create an organization")
def create_organization(
    payload: OrganizationCreateRequest,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return OrganizationService(session).create(payload, firebase_claims)


@router.get("", response_model=list[OrganizationListItem], summary="List organizations for the authenticated user")
def list_organizations(
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return OrganizationService(session).list_for_current_user(firebase_claims)


@router.get("/{organization_id}", response_model=OrganizationResponse, summary="Get an organization")
def get_organization(
    organization_id: UUID,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return OrganizationService(session).get(organization_id, firebase_claims)


@router.patch("/{organization_id}", response_model=OrganizationResponse, summary="Update an organization")
def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdateRequest,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return OrganizationService(session).update(organization_id, payload, firebase_claims)


@router.post("/{organization_id}/onboarding/complete", summary="Mark organization onboarding as complete")
def complete_onboarding(
    organization_id: UUID,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return OrganizationService(session).complete_onboarding(organization_id, firebase_claims)
