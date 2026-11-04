"""LangGraph Generation node backed by GenerationAgent."""

from collections.abc import Callable
from typing import Any

from app.agents.Generation import GenerationAgent
from app.workflows.rag.state import RAGWorkflowState


def create_generation_node(
    agent: GenerationAgent,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a Generation node using an injected application agent.

    Uses the compressed context view when the compression node has produced
    one; otherwise falls back to the original ordered retrieval candidates.
    """

    async def generation_node(state: RAGWorkflowState) -> dict[str, Any]:
        documents = (
            state.get("context_documents")
            if state.get("context_documents") is not None
            else state.get("retrieved_documents") or []
        )
        output = await agent.agenerate(
            current_query=state["query"],
            retrieved_documents=documents,
            conversation_history=state.get("context"),
        )
        return {"generation_output": output}

    return generation_node
