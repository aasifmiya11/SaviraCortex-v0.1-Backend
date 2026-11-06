from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationMembershipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    role: str = "member"

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"admin", "member"}:
            raise ValueError("New memberships can be assigned the admin or member role.")
        return value


class OrganizationMembershipUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"admin", "member"}:
            raise ValueError("Membership role must be admin or member.")
        return value


class OrganizationMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: UUID
    organization_id: UUID
    role: str
    created_at: datetime
    email: str | None = None
    display_name: str | None = None
    custom_roles: list[str] = Field(default_factory=list)

class OrganizationMemberRolesAssignRequest(BaseModel):
    """Custom organization roles to add to an existing member."""

    model_config = ConfigDict(extra="forbid")
    role_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("role_ids")
    @classmethod
    def require_unique_roles(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate role IDs are not allowed.")
        return value
