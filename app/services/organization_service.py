from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMembership, OrganizationRole
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.v1.organizations import (
    OrganizationCreateRequest,
    OrganizationListItem,
    OrganizationResponse,
    OrganizationUpdateRequest,
)


class OrganizationService:
    """Organization operations scoped to the authenticated user's memberships."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = OrganizationRepository(session)

    def _get_user(self, firebase_claims: dict):
        firebase_uid = firebase_claims.get("uid")
        if not isinstance(firebase_uid, str) or not firebase_uid.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The verified Firebase identity is missing a UID.",
            )
        user = self.repository.get_user_by_firebase_uid(firebase_uid)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This Firebase account is not registered in SaviraCortex.",
            )
        return user

    def _get_membership(self, organization_id: UUID, firebase_claims: dict):
        user = self._get_user(firebase_claims)
        membership = self.repository.get_membership(organization_id, user.id)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found or you are not a member of it.",
            )
        return membership

    @staticmethod
    def _response(organization: Organization, role: str) -> OrganizationResponse:
        return OrganizationResponse(
            id=organization.id,
            name=organization.name,
            created_at=organization.created_at,
            role=role,
        )

    def create(self, payload: OrganizationCreateRequest, firebase_claims: dict) -> OrganizationResponse:
        user = self._get_user(firebase_claims)
        organization = Organization(id=uuid4(), name=payload.name)
        membership = OrganizationMembership(
            id=uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role="owner",
        )
        default_role = OrganizationRole(
            id=uuid4(),
            organization_id=organization.id,
            name="Member",
            description="Default role for organization members.",
        )
        try:
            self.repository.create_organization(organization, membership)
            # Persist the organization first so the default role's FK is valid
            # on databases where unrelated pending objects are not dependency-sorted.
            self.session.flush()
            self.session.add(default_role)
            self.session.commit()
            self.session.refresh(organization)
        except Exception:
            self.session.rollback()
            raise
        return self._response(organization, membership.role)

    def list_for_current_user(self, firebase_claims: dict) -> list[OrganizationListItem]:
        user = self._get_user(firebase_claims)
        memberships = self.repository.list_for_user(user.id)
        return [
            OrganizationListItem(
                organization_id=item.organization_id,
                organization_name=item.organization.name,
                role=item.role,
                created_at=item.organization.created_at,
            )
            for item in memberships
        ]

    def get(self, organization_id: UUID, firebase_claims: dict) -> OrganizationResponse:
        membership = self._get_membership(organization_id, firebase_claims)
        organization = self.repository.get_organization(organization_id)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
        return self._response(organization, membership.role)

    def update(
        self,
        organization_id: UUID,
        payload: OrganizationUpdateRequest,
        firebase_claims: dict,
    ) -> OrganizationResponse:
        membership = self._get_membership(organization_id, firebase_claims)
        if membership.role not in {"owner", "admin"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization owners and admins can update organization details.",
            )
        organization = self.repository.get_organization(organization_id)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
        organization.name = payload.name
        try:
            self.session.commit()
            self.session.refresh(organization)
        except Exception:
            self.session.rollback()
            raise
        return self._response(organization, membership.role)
