"""State contract for the persisted single-pass RAG workflow."""

from typing import Annotated, Any, NotRequired, Required, TypedDict
from uuid import UUID

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.agents.Generation.schemas import GenerationOutput
from app.validation.schemas import GenerationValidationResult


class RAGWorkflowState(TypedDict):
    """State passed through validation, retrieval, generation and citation checks."""

    query: Required[str]
    organization_id: Required[UUID]
    user_id: Required[UUID]
    messages: Annotated[list[BaseMessage], add_messages]
    request_id: NotRequired[str]
    long_term_memories: NotRequired[list[dict[str, Any]]]

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


def prior_conversation_messages(state: RAGWorkflowState) -> list[BaseMessage] | None:
    """Return prior turns, excluding this request's current user/assistant messages."""
    request_id = state.get("request_id")
    excluded = {str(request_id), f"assistant:{request_id}"} if request_id else set()
    messages = [
        message
        for message in state.get("messages", [])
        if str(getattr(message, "id", "")) not in excluded
    ]
    return messages or None
