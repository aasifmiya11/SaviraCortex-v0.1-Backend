"""Single-pass LangGraph Retriever node backed by RetrievalOrchestrator."""

from collections.abc import Callable
from typing import Any

from app.services.retrieval.retrieval_service import (
    RetrievalOrchestrationError,
    RetrievalOrchestrator,
)
from app.workflows.rag.state import RAGWorkflowState


def create_retriever_node(
    retriever: RetrievalOrchestrator,
) -> Callable[[RAGWorkflowState], Any]:
    """Create one authorized retrieval/Adaptive-K selection call."""

    async def retriever_node(state: RAGWorkflowState) -> dict[str, Any]:
        retrieval_result = await retriever.retrieve(
            current_query=state["query"],
            organization_id=state["organization_id"],
            user_id=state["user_id"],
            conversation_history=state.get("context"),
        )

        if retrieval_result.get("candidate_generation_error"):
            raise RetrievalOrchestrationError(
                "Authorized document candidate generation failed."
            )

        selected_documents = retrieval_result["selected_candidates"]
        diagnostics = {
            "attempt": 1,
            "selected_count": retrieval_result.get(
                "selected_count", len(selected_documents)
            ),
            "eligible_count": retrieval_result.get("eligible_count"),
            "fused_count": retrieval_result.get("fused_count"),
            "reranked_count": retrieval_result.get("reranked_count"),
            "branch_count": retrieval_result.get("branch_count"),
            "retrieval_reason": retrieval_result.get("retrieval_reason"),
            "candidate_generation_error": None,
            "expansion": retrieval_result.get("expansion"),
        }

        return {
            "retrieved_documents": selected_documents,
            "retrieval_attempt": 1,
            "retrieval_reason": retrieval_result.get("retrieval_reason"),
            "retrieval_diagnostics": {
                "total_attempts": 1,
                "attempts": [diagnostics],
            },
        }

    return retriever_node
