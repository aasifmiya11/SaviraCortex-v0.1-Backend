from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import OrganizationDepartment
from app.repositories.department_repository import DepartmentRepository
from app.schemas.v1.departments import DepartmentCreateRequest, DepartmentResponse


class DepartmentService:
    """Organization-scoped department operations with membership authorization."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = DepartmentRepository(session)

    def _authorized_membership(self, organization_id: UUID, firebase_claims: dict):
        firebase_uid = firebase_claims.get("uid")
        if not isinstance(firebase_uid, str) or not firebase_uid.strip():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The verified Firebase identity is missing a UID.")
        user = self.repository.get_user_by_firebase_uid(firebase_uid)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This Firebase account is not registered in SaviraCortex.")
        membership = self.repository.get_membership(organization_id, user.id)
        if membership is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found or you are not a member of it.")
        return membership

    def list_departments(self, organization_id: UUID, firebase_claims: dict) -> list[DepartmentResponse]:
        self._authorized_membership(organization_id, firebase_claims)
        return [DepartmentResponse.model_validate(item) for item in self.repository.list_departments(organization_id)]

    def create_department(self, organization_id: UUID, payload: DepartmentCreateRequest, firebase_claims: dict) -> DepartmentResponse:
        membership = self._authorized_membership(organization_id, firebase_claims)
        if membership.role not in {"owner", "admin"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only organization owners and admins can create departments.")
        department = OrganizationDepartment(
            id=uuid4(), organization_id=organization_id,
            name=payload.name, description=payload.description,
        )
        try:
            self.repository.create_department(department)
            self.session.commit()
            self.session.refresh(department)
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A department with this name already exists in this organization.") from exc
        except Exception:
            self.session.rollback()
            raise
        return DepartmentResponse.model_validate(department)
