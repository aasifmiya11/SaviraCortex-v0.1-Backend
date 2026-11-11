from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.Generation.schemas import GenerationStatus
from app.validation.schemas import CitationReference


class ConversationTurnRequest(BaseModel):
    """Legacy internal request type retained for isolated generation-agent tests."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Conversation content cannot be blank.")
        return value


class GenerationRequest(BaseModel):
    """Input for one organization-scoped, backend-managed conversation turn."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=8000)
    conversation_id: UUID | None = None
    checkpoint_id: str | None = Field(default=None, max_length=255)
    path_group_id: UUID | None = None
    path_id: UUID | None = None
    request_id: UUID | None = None
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None
    pii_action: Literal["redact", "send_as_is", "reject"] | None = None

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Query cannot be blank.")
        return value


class GenerationResponse(BaseModel):
    """Markdown answer plus trusted citation metadata and conversation identity."""

    model_config = ConfigDict(extra="forbid")

    generation_id: UUID | None = None
    conversation_id: UUID | None = None
    checkpoint_id: str | None = None
    checkpoint_thread_id: str | None = None
    path_group_id: UUID | None = None
    path_id: UUID | None = None
    request_id: UUID | None = None
    query: str
    answer: str
    status: GenerationStatus
    citations: list[CitationReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    retrieval_attempts: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    guardrail_decision: Literal["blocked", "redirected", "redacted"] | None = None
    guardrail_categories: list[str] = Field(default_factory=list)


class GenerationFeedbackRequest(BaseModel):
    """Human relevance judgment for one generated answer."""

    model_config = ConfigDict(extra="forbid")

    feedback_status: Literal["relevant", "not_relevant"]
