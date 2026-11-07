from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentVersionLibraryItem(BaseModel):
    id: UUID
    version_number: int
    version_label: str | None = None
    original_filename: str
    summary: str | None = None
    status: str
    page_count: int | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    supersedes_version_id: UUID | None = None
    created_at: datetime


class DocumentLibraryItem(BaseModel):
    id: UUID
    title: str
    document_type: str
    description: str | None = None
    department_id: UUID | None = None
    department_name: str | None = None
    archived: bool
    created_at: datetime
    active_version_id: UUID | None = None
    versions: list[DocumentVersionLibraryItem] = Field(default_factory=list)


class DocumentLibraryResponse(BaseModel):
    items: list[DocumentLibraryItem]
    total: int
    limit: int
    offset: int


class DocumentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    document_type: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=10000)
    department_id: UUID | None = None
    archived: bool | None = None

    @field_validator("title", "document_type", "description")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one document field to update.")
        if "title" in self.model_fields_set and not self.title:
            raise ValueError("Title cannot be blank.")
        if "document_type" in self.model_fields_set and not self.document_type:
            raise ValueError("Document type cannot be blank.")
        return self


class DocumentVersionSummaryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=20000)

    @field_validator("summary")
    @classmethod
    def trim_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Summary cannot be blank.")
        return value


class DocumentVersionSummaryUpdateResponse(BaseModel):
    version: DocumentVersionLibraryItem
    summary_index_synced: bool
