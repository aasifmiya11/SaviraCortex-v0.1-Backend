"""LangGraph Context Compression node backed by ContextCompressionAgent."""

from collections.abc import Callable
from typing import Any

from app.agents.Context_compression import ContextCompressionAgent
from app.workflows.rag.state import RAGWorkflowState


def create_context_compression_node(
    agent: ContextCompressionAgent,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a conditional compression node using an injected agent.

    Original retrieval candidates remain untouched in retrieved_documents.
    The compressed one-to-one view is stored separately in context_documents.
    """

    async def context_compression_node(state: RAGWorkflowState) -> dict[str, Any]:
        documents = state.get("retrieved_documents") or []
        if not documents:
            return {
                "context_documents": [],
                "context_compressed": False,
                "context_token_estimate": 0,
            }

        token_estimate = agent.estimate_token_count(state["query"], documents)
        if token_estimate <= agent.config.token_threshold:
            return {
                "context_documents": documents,
                "context_compressed": False,
                "context_token_estimate": token_estimate,
            }

        compressed_documents = await agent.acompress(
            current_query=state["query"],
            retrieved_documents=documents,
        )
        return {
            "context_documents": compressed_documents,
            "context_compressed": True,
            "context_token_estimate": token_estimate,
        }

    return context_compression_node
