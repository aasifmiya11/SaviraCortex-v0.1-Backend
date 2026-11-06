from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentIngestionCandidate(BaseModel):
    document_id: UUID
    version_id: UUID
    version_number: int
    title: str
    status: str
    similarity_score: float | None = None
    matched_by: str | None = None


class DocumentIngestionAnalysisResponse(BaseModel):
    status: Literal["ready_for_review", "duplicate"]
    ingestion_session_id: UUID | None = None
    original_filename: str
    file_size: int
    file_hash: str
    content_hash: str
    page_count: int
    title: str | None = None
    document_type: str | None = None
    description: str | None = None
    summary: str | None = None
    matching_classification: str
    matching_candidates: list[DocumentIngestionCandidate] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class DocumentIngestionFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["new", "supersede", "independent", "reject"]
    title: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=10000)
    department_id: UUID | None = None
    archived: bool = False
    target_document_id: UUID | None = None

    @field_validator("title", "document_type", "description")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field cannot be blank.")
        return value.strip()


class DocumentIngestionFinalizeResponse(BaseModel):
    status: Literal["registered_pending", "rejected"]
    document_id: UUID | None = None
    document_version_id: UUID | None = None
    version_number: int | None = None
    version_status: str | None = None
    archived: bool | None = None
