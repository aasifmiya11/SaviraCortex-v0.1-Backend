from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.schemas.v1.departments import DepartmentCreateRequest, DepartmentResponse
from app.services.department_service import DepartmentService

router = APIRouter(prefix="/organizations/{organization_id}/departments", tags=["Departments"])


@router.get("", response_model=list[DepartmentResponse], summary="List departments in an organization")
def list_departments(
    organization_id: UUID,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return DepartmentService(session).list_departments(organization_id, firebase_claims)


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED, summary="Create a department in an organization")
def create_department(
    organization_id: UUID,
    payload: DepartmentCreateRequest,
    session: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    return DepartmentService(session).create_department(organization_id, payload, firebase_claims)
