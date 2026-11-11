"""Single-pass LangGraph Retriever node backed by RetrievalOrchestrator."""

from collections.abc import Callable
from typing import Any

from app.guardrails.runtime_schemas import resolve_effective_policy
from app.services.retrieval.retrieval_service import (
    RetrievalOrchestrationError,
    RetrievalOrchestrator,
)
from app.workflows.rag.state import (
    RAGWorkflowState,
    prior_conversation_messages,
)


def create_retriever_node(
    retriever: RetrievalOrchestrator,
) -> Callable[[RAGWorkflowState], Any]:
    """Create one authorized retrieval/Adaptive-K selection call."""

    async def retriever_node(state: RAGWorkflowState) -> dict[str, Any]:
        retrieval_result = await retriever.retrieve(
            current_query=state["query"],
            organization_id=state["organization_id"],
            user_id=state["user_id"],
            conversation_history=prior_conversation_messages(state),
        )

        if retrieval_result.get("candidate_generation_error"):
            raise RetrievalOrchestrationError(
                "Authorized document candidate generation failed."
            )

        selected_documents = retrieval_result["selected_candidates"]
        policy = resolve_effective_policy(state.get("effective_guardrail_policy") or {})
        if policy.retrieval_guardrails_enabled:
            # Chunks flagged during ingestion are excluded before they can enter
            # compression, evidence evaluation, prompts, or generation.
            selected_documents = [
                item for item in selected_documents
                if not (
                    isinstance(item, dict)
                    and isinstance(item.get("metadata"), dict)
                    and item["metadata"].get("prompt_injection_flagged") is True
                )
            ]
        diagnostics = {
            "attempt": 1,
            "selected_count": len(selected_documents),
            "eligible_count": retrieval_result.get("eligible_count"),
            "fused_count": retrieval_result.get("fused_count"),
            "reranked_count": retrieval_result.get("reranked_count"),
            "branch_count": retrieval_result.get("branch_count"),
            "retrieval_reason": retrieval_result.get("retrieval_reason"),
            "candidate_generation_error": None,
            "expansion": retrieval_result.get("expansion"),
        }

        generated_queries = retrieval_result.get("generated_queries") or []
        retrieval_trace = {
            "generated_queries": generated_queries,
            "generated_query_count": len(generated_queries),
            "mode": retrieval_result.get("mode"),
            "top_k": retrieval_result.get("top_k"),
            "candidate_k": retrieval_result.get("candidate_k"),
            "branch_count": retrieval_result.get("branch_count", 0),
            "branches": retrieval_result.get("branches") or [],
            "fused_count": retrieval_result.get("fused_count", 0),
            "reranked_count": retrieval_result.get("reranked_count", 0),
            "eligible_count": retrieval_result.get("eligible_count", 0),
            "selected_count": len(selected_documents),
            "expansion": retrieval_result.get("expansion") or {},
            "retrieval_reason": retrieval_result.get("retrieval_reason"),
        }

        return {
            "retrieved_documents": selected_documents,
            "retrieval_attempt": 1,
            "retrieval_reason": retrieval_result.get("retrieval_reason"),
            "retrieval_diagnostics": {
                "total_attempts": 1,
                "attempts": [diagnostics],
            },
            "retrieval_trace": retrieval_trace,
        }

    return retriever_node
