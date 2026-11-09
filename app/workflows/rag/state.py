"""Minimal state contract for the single-pass RAG workflow."""

from typing import Any, NotRequired, Required, TypedDict
from uuid import UUID

from langchain_core.messages import BaseMessage

from app.agents.Generation.schemas import GenerationOutput
from app.validation.schemas import GenerationValidationResult


class RAGWorkflowState(TypedDict):
    """State passed through validation, retrieval, generation, and citation checks."""

    query: Required[str]
    organization_id: Required[UUID]
    user_id: Required[UUID]
    context: NotRequired[list[BaseMessage] | None]

    is_valid: NotRequired[bool]
    validation_error: NotRequired[str | None]

    # Exact selected chunk list returned by the first Adaptive-K selection.
    retrieved_documents: NotRequired[list[dict[str, Any]]]
    retrieval_attempt: NotRequired[int]
    retrieval_reason: NotRequired[str | None]
    retrieval_diagnostics: NotRequired[dict[str, Any] | None]
    retrieval_trace: NotRequired[dict[str, Any] | None]

    generation_output: NotRequired[GenerationOutput | None]
    validation_result: NotRequired[GenerationValidationResult | None]
    errors: NotRequired[list[str]]
