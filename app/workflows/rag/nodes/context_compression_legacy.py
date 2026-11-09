"""LangGraph Context Compression node backed by ContextCompressionAgent."""

from collections.abc import Callable
from typing import Any

from app.agents.Context_compression_legacy import ContextCompressionAgent
from app.workflows.rag.state import RAGWorkflowState


def create_context_compression_node(
    agent: ContextCompressionAgent,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a compression node.

    Graph routing is responsible for invoking this node only when the
    accumulated document count exceeds the configured workflow threshold.
    Once invoked, every document is compressed one-to-one. The original
    retrieval candidates remain untouched.
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
