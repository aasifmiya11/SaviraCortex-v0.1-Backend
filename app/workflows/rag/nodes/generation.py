"""LangGraph Generation node backed by GenerationAgent."""

from collections.abc import Callable
from typing import Any

from app.agents.Generation import GenerationAgent
from app.workflows.rag.state import RAGWorkflowState


def create_generation_node(
    agent: GenerationAgent,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a Generation node using an injected application agent.

    The node passes the original validated query, accumulated ranked evidence,
    and optional conversation history to the existing Generation Agent.
    Retrieval and static post-generation validation remain separate nodes.
    """

    async def generation_node(state: RAGWorkflowState) -> dict[str, Any]:
        output = await agent.agenerate(
            current_query=state["query"],
            retrieved_documents=state.get("retrieved_documents") or [],
            conversation_history=state.get("context"),
        )
        return {"generation_output": output}

    return generation_node
