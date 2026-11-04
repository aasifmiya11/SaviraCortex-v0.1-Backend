"""LangGraph Retrieval Expansion node backed by RetrievalExpansionAgent."""

from collections.abc import Callable
from typing import Any

from app.agents.Retrieval_expansion import RetrievalExpansionAgent
from app.workflows.rag.state import RAGWorkflowState


def create_retrieval_expansion_node(
    agent: RetrievalExpansionAgent,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a node using an application-configured expansion agent.

    Graph routing must enforce the retrieval-attempt limit before this node
    is invoked. This node only requests expansion and stores both outputs.
    """

    async def retrieval_expansion_node(
        state: RAGWorkflowState,
    ) -> dict[str, Any]:
        expansion = await agent.aexpand(
            original_query=state["query"],
            current_retrieval_query=(
                state.get("rewritten_query") or state["query"]
            ),
            missing_information=state.get("missing_information") or [],
            retrieved_documents=state.get("retrieved_documents") or [],
            conversation_history=state.get("context"),
        )

        return {
            "rewritten_query": expansion.rewritten_query,
            "hypothetical_answer": expansion.hypothetical_answer,
        }

    return retrieval_expansion_node
