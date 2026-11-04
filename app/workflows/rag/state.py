"""Shared state contract for the end-to-end RAG LangGraph workflow.

The workflow keeps the user's cleaned query immutable. Retrieval expansion
updates rewritten_query and hypothetical_answer; those values are used only
to form subsequent retrieval requests.
"""

from typing import Any, NotRequired, Required, TypedDict
from uuid import UUID

from langchain_core.messages import BaseMessage

from app.agents.Generation.schemas import GenerationOutput
from app.validation.schemas import GenerationValidationResult


class RAGWorkflowState(TypedDict):
    """State passed between nodes in the RAG workflow.

    Required input fields are supplied when the graph is invoked. All other
    fields are optional because LangGraph nodes populate them progressively.
    """

    # Immutable request inputs. The Input Validator replaces query with its
    # cleaned form after successful validation.
    query: Required[str]
    organization_id: Required[UUID]
    user_id: Required[UUID]
    context: NotRequired[list[BaseMessage] | None]

    # Input validation.
    is_valid: NotRequired[bool]

    # Retrieval results accumulated across retrieval attempts.
    retrieved_documents: NotRequired[list[dict[str, Any]]]
    excluded_chunk_ids: NotRequired[list[str]]
    exclude: NotRequired[bool]
    retrieval_attempt: NotRequired[int]
    retrieval_diagnostics: NotRequired[dict[str, Any] | None]

    # Evidence evaluation and retry control.
    is_sufficient: NotRequired[bool | None]
    missing_information: NotRequired[list[str]]
    retry: NotRequired[bool]

    # Retrieval Expansion Agent output. These never replace query.
    rewritten_query: NotRequired[str | None]
    hypothetical_answer: NotRequired[str | None]

    # Generation and deterministic post-generation validation.
    generation_output: NotRequired[GenerationOutput | None]
    validation_result: NotRequired[GenerationValidationResult | None]

    # Workflow-level errors collected by nodes.
    errors: NotRequired[list[str]]
