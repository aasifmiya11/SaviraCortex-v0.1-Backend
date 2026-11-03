
from uuid import UUID

from app.repositories.authorization_repository import (
    AuthorizationRepository,
)


class AuthorizationService:
    def __init__(self, repository: AuthorizationRepository):
        self.repository = repository

    def get_authorized_document_ids(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[UUID]:
        if not isinstance(organization_id, UUID):
            raise ValueError("organization_id must be a UUID.")

        if not isinstance(user_id, UUID):
            raise ValueError("user_id must be a UUID.")

        return self.repository.get_authorized_document_ids(
            organization_id=organization_id,
            user_id=user_id,
        )
