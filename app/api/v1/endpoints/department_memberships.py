from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.schemas.v1.department_memberships import DepartmentMembershipCreateRequest, DepartmentMembershipResponse
from app.services.membership_service import MembershipService

router = APIRouter(
    prefix="/organizations/{organization_id}/departments/{department_id}/members",
    tags=["Department memberships"],
)


@router.get("", response_model=list[DepartmentMembershipResponse], summary="List members assigned to a department")
def list_department_members(organization_id: UUID, department_id: UUID, session: Session = Depends(get_db), firebase_claims: dict = Depends(get_verified_firebase_claims)):
    return MembershipService(session).list_department_members(organization_id, department_id, firebase_claims)


@router.post("", response_model=DepartmentMembershipResponse, status_code=status.HTTP_201_CREATED, summary="Assign an organization member to a department")
def assign_department_member(organization_id: UUID, department_id: UUID, payload: DepartmentMembershipCreateRequest, session: Session = Depends(get_db), firebase_claims: dict = Depends(get_verified_firebase_claims)):
    return MembershipService(session).assign_department(organization_id, department_id, payload.user_id, firebase_claims)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a user from a department")
def unassign_department_member(organization_id: UUID, department_id: UUID, user_id: UUID, session: Session = Depends(get_db), firebase_claims: dict = Depends(get_verified_firebase_claims)):
    MembershipService(session).unassign_department(organization_id, department_id, user_id, firebase_claims)
    return Response(status_code=status.HTTP_204_NO_CONTENT)