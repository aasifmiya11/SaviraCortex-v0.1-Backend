from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OrganizationSetupItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Name must contain at least 2 non-whitespace characters.")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class OrganizationSignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_name: str = Field(min_length=2, max_length=255)
    admin_name: str = Field(min_length=2, max_length=255)
    departments: list[OrganizationSetupItem] = Field(min_length=1, max_length=100)
    roles: list[OrganizationSetupItem] = Field(min_length=1, max_length=100)

    @field_validator("organization_name", "admin_name")
    @classmethod
    def strip_and_validate(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Must contain at least 2 non-whitespace characters.")
        return value

    @model_validator(mode="after")
    def validate_unique_setup_names(self):
        for field_name in ("departments", "roles"):
            items = getattr(self, field_name)
            names = [item.name.casefold() for item in items]
            if len(set(names)) != len(names):
                raise ValueError(f"{field_name.capitalize()} names must be unique within the organization.")
        return self


class OrganizationSignupResponse(BaseModel):
    message: str
    user_id: str
    organization_id: str
    role: Literal["owner", "admin", "member"]


class OrganizationMembershipSummary(BaseModel):
    organization_id: str
    organization_name: str
    role: Literal["owner", "admin", "member"]
    onboarding_completed: bool = False


class AuthenticatedUserResponse(BaseModel):
    user_id: str
    firebase_uid: str
    email: str | None
    phone_number: str | None
    display_name: str | None
    sign_in_provider: str | None
    organizations: list[OrganizationMembershipSummary]
