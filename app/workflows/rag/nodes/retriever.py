"""LangGraph Retriever node backed by the existing RetrievalOrchestrator."""

from collections.abc import Callable
from typing import Any

from app.services.retrieval.retrieval_service import RetrievalOrchestrator
from app.workflows.rag.state import RAGWorkflowState


def create_retriever_node(
    retriever: RetrievalOrchestrator,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a Retriever node using an application-configured orchestrator.

    The orchestrator is injected because its dependencies (authorization,
    query generation, vector retrieval, fusion, and reranking) are managed by
    the application composition layer, not constructed inside a graph node.
    """

    async def retriever_node(state: RAGWorkflowState) -> dict[str, Any]:
        previously_retrieved = list(state.get("retrieved_documents") or [])
        exclude = state.get("exclude", False)

        if exclude:
            rewritten_query = state.get("rewritten_query")
            hypothetical_answer = state.get("hypothetical_answer")

            if not rewritten_query or not hypothetical_answer:
                raise ValueError(
                    "rewritten_query and hypothetical_answer are required "
                    "when exclude is True."
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

        if not exclude:
            accumulated_documents = newly_retrieved
        else:
            existing_chunk_ids = {
                document.get("chunk_id")
                for document in previously_retrieved
                if document.get("chunk_id")
            }
            accumulated_documents = previously_retrieved + [
                document
                for document in newly_retrieved
                if document.get("chunk_id") not in existing_chunk_ids
            ]

        return {"retrieved_documents": accumulated_documents}

    return retriever_node
