from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.schemas.v1.invitations import (
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationCreateRequest,
    InvitationCreateResponse,
    InvitationListItem,
    InvitationPreviewRequest,
    InvitationPreviewResponse,
)
from app.services.invitation_service import InvitationService

router = APIRouter(tags=["Organization invitations"])


@router.get("/invitations/preview", response_model=InvitationPreviewResponse)
def preview_invitation(token: str, session: Session = Depends(get_db)):
    return InvitationService(session).preview(token)


@router.post("/invitations/accept", response_model=InvitationAcceptResponse, status_code=201)
def accept_invitation(
    payload: InvitationAcceptRequest,
    session: Session = Depends(get_db),
):
    return InvitationService(session).accept(payload)


@router.get(
    "/organizations/{organization_id}/invitations",
    response_model=list[InvitationListItem],
)
def list_invitations(
    organization_id: UUID,
    session: Session = Depends(get_db),
    claims: dict = Depends(get_verified_firebase_claims),
):
    return InvitationService(session).list_for_organization(organization_id, claims)


@router.post(
    "/organizations/{organization_id}/invitations",
    response_model=InvitationCreateResponse,
    status_code=201,
)
def create_invitation(
    organization_id: UUID,
    payload: InvitationCreateRequest,
    session: Session = Depends(get_db),
    claims: dict = Depends(get_verified_firebase_claims),
):
    return InvitationService(session).create(organization_id, payload, claims)


@router.post("/invitations/preview", response_model=InvitationPreviewResponse)
def preview_invitation_body(
    payload: InvitationPreviewRequest,
    session: Session = Depends(get_db),
):
    return InvitationService(session).preview(payload.token)
