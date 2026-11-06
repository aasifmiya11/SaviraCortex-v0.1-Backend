from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.schemas.v1.memberships import (
    OrganizationMemberRolesAssignRequest,
    OrganizationMembershipCreateRequest,
    OrganizationMembershipResponse,
    OrganizationMembershipUpdateRequest,
)
from app.schemas.v1.organization_roles import OrganizationRoleResponse
from app.services.membership_service import MembershipService

router = APIRouter(prefix="/organizations/{organization_id}/members", tags=["Organization memberships"])


@router.get("", response_model=list[OrganizationMembershipResponse], summary="List organization members")
def list_members(organization_id: UUID, session: Session = Depends(get_db), firebase_claims: dict = Depends(get_verified_firebase_claims)):
    return MembershipService(session).list_members(organization_id, firebase_claims)


@router.post("", response_model=OrganizationMembershipResponse, status_code=status.HTTP_201_CREATED, summary="Add an existing SaviraCortex user to an organization")
def add_member(organization_id: UUID, payload: OrganizationMembershipCreateRequest, session: Session = Depends(get_db), firebase_claims: dict = Depends(get_verified_firebase_claims)):
    return MembershipService(session).add_member(organization_id, payload.user_id, payload.role, firebase_claims)


@router.patch("/{user_id}", response_model=OrganizationMembershipResponse, summary="Update an organization membership role")
def update_member(organization_id: UUID, user_id: UUID, payload: OrganizationMembershipUpdateRequest, session: Session = Depends(get_db), firebase_claims: dict = Depends(get_verified_firebase_claims)):
    return MembershipService(session).update_member(organization_id, user_id, payload.role, firebase_claims)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a member from an organization")
def remove_member(organization_id: UUID, user_id: UUID, session: Session = Depends(get_db), firebase_claims: dict = Depends(get_verified_firebase_claims)):
    MembershipService(session).remove_member(organization_id, user_id, firebase_claims)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post(
    "/{user_id}/roles",
    response_model=list[OrganizationRoleResponse],
    summary="Assign multiple custom organization roles to a member",
)
def assign_member_roles(
    organization_id: UUID,
    user_id: UUID,
    payload: OrganizationMemberRolesAssignRequest,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return MembershipService(session).assign_custom_roles(
        organization_id, user_id, payload.role_ids, firebase_claims
    )
