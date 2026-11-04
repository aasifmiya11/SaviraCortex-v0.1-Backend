"""LangGraph Retriever node backed by the existing RetrievalOrchestrator."""

from collections.abc import Callable
from typing import Any

from app.services.retrieval.retrieval_service import RetrievalOrchestrator
from app.workflows.rag.state import RAGWorkflowState


def create_retriever_node(
    retriever: RetrievalOrchestrator,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a Retriever node using an application-configured orchestrator."""

    async def retriever_node(state: RAGWorkflowState) -> dict[str, Any]:
        previously_retrieved = list(state.get("retrieved_documents") or [])
        attempt_before_call = state.get("retrieval_attempt", 0)
        exclude = attempt_before_call > 0

        if exclude:
            rewritten_query = state.get("rewritten_query")
            hypothetical_answer = state.get("hypothetical_answer")
            if not rewritten_query or not hypothetical_answer:
                raise ValueError(
                    "rewritten_query and hypothetical_answer are required "
                    "for retrieval attempts after the first."
                )

            current_query = (
                "The previous retrieval results were insufficient to answer "
                "the user's question completely. Generate contextualized "
                "retrieval queries that focus on the specific missing "
                "requirement described below. Do not simply repeat searches "
                "for information already retrieved. Treat the hypothetical "
                "answer only as semantic guidance for retrieval, not as "
                "verified evidence.\n\n"
                f"Original user question:\n{state['query']}\n\n"
                f"Rewritten query (focus of the next retrieval):\n"
                f"{rewritten_query}\n\n"
                f"Hypothetical answer (additional retrieval context only):\n"
                f"{hypothetical_answer}"
            )
            excluded_chunk_ids = list(
                dict.fromkeys(
                    document["chunk_id"]
                    for document in previously_retrieved
                    if isinstance(document.get("chunk_id"), str)
                    and document["chunk_id"]
                )
            )
        else:
            current_query = state["query"]
            excluded_chunk_ids = None

        retrieval_result = await retriever.retrieve(
            current_query=current_query,
            organization_id=state["organization_id"],
            user_id=state["user_id"],
            conversation_history=state.get("context"),
            exclude=exclude,
            excluded_chunk_ids=excluded_chunk_ids,
        )

        newly_retrieved = retrieval_result["selected_candidates"]
        accumulated_documents = list(previously_retrieved)
        known_chunk_ids = {
            document.get("chunk_id")
            for document in previously_retrieved
            if document.get("chunk_id")
        }

        for document in newly_retrieved:
            chunk_id = document.get("chunk_id")
            if chunk_id and chunk_id in known_chunk_ids:
                continue
            accumulated_documents.append(document)
            if chunk_id:
                known_chunk_ids.add(chunk_id)

        all_excluded_chunk_ids = list(
            dict.fromkeys(
                document["chunk_id"]
                for document in accumulated_documents
                if isinstance(document.get("chunk_id"), str)
                and document["chunk_id"]
            )
        )

        attempt = attempt_before_call + 1
        diagnostics = {
            "attempt": attempt,
            "selected_count": retrieval_result.get(
                "selected_count", len(newly_retrieved)
            ),
            "eligible_count": retrieval_result.get("eligible_count"),
            "fused_count": retrieval_result.get("fused_count"),
            "reranked_count": retrieval_result.get("reranked_count"),
            "branch_count": retrieval_result.get("branch_count"),
            "retrieval_reason": retrieval_result.get("retrieval_reason"),
            "candidate_generation_error": retrieval_result.get(
                "candidate_generation_error"
            ),
            "expansion": retrieval_result.get("expansion"),
        }
        previous_diagnostics = state.get("retrieval_diagnostics") or {}
        diagnostic_attempts = list(previous_diagnostics.get("attempts") or [])
        diagnostic_attempts.append(diagnostics)

        return {
            "retrieved_documents": accumulated_documents,
            "excluded_chunk_ids": all_excluded_chunk_ids,
            "retrieval_attempt": attempt,
            "retrieval_diagnostics": {
                "total_attempts": attempt,
                "attempts": diagnostic_attempts,
            },
            "exclude": exclude,
            "retry": False,
            "context_compressed": False,
        }

    return retriever_node
