from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.schemas.v1.organization_roles import OrganizationRoleCreateRequest, OrganizationRoleResponse
from app.services.organization_role_service import OrganizationRoleService

router = APIRouter(
    prefix="/organizations/{organization_id}/roles",
    tags=["Organization roles"],
)


@router.get("", response_model=list[OrganizationRoleResponse], summary="List custom roles")
def list_roles(
    organization_id: UUID,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return OrganizationRoleService(session).list_roles(organization_id, firebase_claims)


@router.post(
    "",
    response_model=OrganizationRoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom organization role",
)
def create_role(
    organization_id: UUID,
    payload: OrganizationRoleCreateRequest,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return OrganizationRoleService(session).create_role(organization_id, payload, firebase_claims)
