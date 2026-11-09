from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.Generation.schemas import GenerationStatus
from app.validation.schemas import CitationReference


class ConversationTurnRequest(BaseModel):
    """A client-held conversation turn; system instructions are never accepted."""

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
    """Input for one organization-scoped RAG generation request."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=8000)
    conversation_history: list[ConversationTurnRequest] = Field(
        default_factory=list,
        max_length=20,
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Query cannot be blank.")
        return value

    @model_validator(mode="after")
    def validate_history_size(self) -> "GenerationRequest":
        total_characters = sum(len(turn.content) for turn in self.conversation_history)
        if total_characters > 40000:
            raise ValueError("Conversation history cannot exceed 40,000 characters.")
        return self


class GenerationResponse(BaseModel):
    """Markdown answer plus trusted, request-scoped citation metadata."""

    model_config = ConfigDict(extra="forbid")

    generation_id: UUID
    query: str
    answer: str
    status: GenerationStatus
    citations: list[CitationReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    retrieval_attempts: int = Field(ge=0)
    evidence_count: int = Field(ge=0)



class GenerationFeedbackRequest(BaseModel):
    """Human relevance judgment for one generated answer."""

    model_config = ConfigDict(extra="forbid")

    feedback_status: Literal["relevant", "not_relevant"]
