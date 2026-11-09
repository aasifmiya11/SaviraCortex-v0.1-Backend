from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class InvitationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    candidate_name: str = Field(min_length=2, max_length=255)
    role: Literal["admin", "member"] = "member"
    role_ids: list[UUID] = Field(default_factory=list, max_length=100)
    department_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("candidate_name")
    @classmethod
    def normalize_candidate_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Candidate name must contain at least 2 characters.")
        return value

    @field_validator("role_ids", "department_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate selections are not allowed.")
        return value


class InvitationCreateResponse(BaseModel):
    id: UUID
    email: str
    candidate_name: str
    role: str
    custom_role: str = "Member"
    status: str
    expires_at: datetime
    email_sent_at: datetime


class InvitationListItem(BaseModel):
    id: UUID
    email: str
    candidate_name: str
    role: str
    custom_role: str = "Member"
    status: str
    created_at: datetime
    expires_at: datetime
    email_sent_at: datetime | None


class InvitationPreviewResponse(BaseModel):
    email: str
    candidate_name: str
    organization_name: str
    expires_at: datetime


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=256)
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    phone_number: str | None = Field(default=None, max_length=30)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Full name must contain at least 2 characters.")
        return value

    @field_validator("phone_number")
    @classmethod
    def normalize_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class InvitationAcceptResponse(BaseModel):
    message: str
    user_id: UUID
    organization_id: UUID
    role: str
    custom_token: str


class InvitationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=256)
