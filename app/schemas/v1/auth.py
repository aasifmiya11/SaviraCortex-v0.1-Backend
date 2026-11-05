from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationSignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_name: str = Field(min_length=2, max_length=255)
    admin_name: str = Field(min_length=2, max_length=255)

    @field_validator("organization_name", "admin_name")
    @classmethod
    def strip_and_validate(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Must contain at least 2 non-whitespace characters.")
        return value


class OrganizationSignupResponse(BaseModel):
    message: str
    user_id: str
    organization_id: str
    role: Literal["owner", "admin", "member"]


class OrganizationMembershipSummary(BaseModel):
    organization_id: str
    organization_name: str
    role: Literal["owner", "admin", "member"]


class AuthenticatedUserResponse(BaseModel):
    user_id: str
    firebase_uid: str
    email: str | None
    phone_number: str | None
    display_name: str | None
    sign_in_provider: str | None
    organizations: list[OrganizationMembershipSummary]
