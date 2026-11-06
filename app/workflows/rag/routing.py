"""Conditional routing functions for the RAG workflow."""

from typing import Any

from app.workflows.rag.config import RAGWorkflowConfig
from app.workflows.rag.state import RAGWorkflowState


def route_after_validation(state: RAGWorkflowState) -> str:
    """Route valid queries to retrieval and invalid queries directly to END."""
    return "valid" if state.get("is_valid") is True else "invalid"


def route_after_evaluation(
    state: RAGWorkflowState,
    config: RAGWorkflowConfig | None = None,
) -> str:
    """Choose expansion, compression, or generation after evidence evaluation.

    The attempt limit is checked before Retrieval Expansion can be invoked.
    Compression is selected only when accumulated documents exceed the
    configured document-count threshold. If PostgreSQL authorizes no document
    versions for this member, another retrieval attempt cannot add evidence.
    """
    workflow_config = config or RAGWorkflowConfig()

    diagnostics: Any = state.get("retrieval_diagnostics") or {}
    attempts = diagnostics.get("attempts") or []
    if attempts and attempts[-1].get("retrieval_reason") == (
        "no_authorized_document_versions"
    ):
        return "generate"

    is_sufficient = state.get("is_sufficient") is True
    retrieval_attempt = state.get("retrieval_attempt", 0)

    if (
        not is_sufficient
        and retrieval_attempt < workflow_config.max_retrieval_attempts
    ):
        return "expand"

    documents: Any = state.get("retrieved_documents") or []
    if len(documents) > workflow_config.compression_document_threshold:
        return "compress"

    return "generate"
