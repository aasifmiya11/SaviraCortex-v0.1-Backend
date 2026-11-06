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