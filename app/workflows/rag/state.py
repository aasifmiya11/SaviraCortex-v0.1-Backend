"""Shared state contract for the end-to-end RAG LangGraph workflow.

Original retrieval candidates remain available for retrieval expansion and
provenance. Context compression creates a separate ordered view for evidence
evaluation, generation, and citation validation.
"""

from typing import Any, NotRequired, Required, TypedDict
from uuid import UUID

from langchain_core.messages import BaseMessage

from app.agents.Generation.schemas import GenerationOutput
from app.validation.schemas import GenerationValidationResult


class RAGWorkflowState(TypedDict):
    """State passed between nodes in the RAG workflow."""

    query: Required[str]
    organization_id: Required[UUID]
    user_id: Required[UUID]
    context: NotRequired[list[BaseMessage] | None]

    is_valid: NotRequired[bool]
    validation_error: NotRequired[str | None]

    retrieved_documents: NotRequired[list[dict[str, Any]]]
    excluded_chunk_ids: NotRequired[list[str]]
    exclude: NotRequired[bool]
    retrieval_attempt: NotRequired[int]
    retrieval_diagnostics: NotRequired[dict[str, Any] | None]

    # One-to-one query-focused view; order and metadata match original docs.
    context_documents: NotRequired[list[dict[str, Any]]]
    context_compressed: NotRequired[bool]
    context_token_estimate: NotRequired[int]

    is_sufficient: NotRequired[bool | None]
    missing_information: NotRequired[list[str]]
    retry: NotRequired[bool]

    rewritten_query: NotRequired[str | None]
    hypothetical_answer: NotRequired[str | None]

    generation_output: NotRequired[GenerationOutput | None]
    validation_result: NotRequired[GenerationValidationResult | None]
    errors: NotRequired[list[str]]
