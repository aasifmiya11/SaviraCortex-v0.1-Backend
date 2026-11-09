"""LangGraph Generation node backed by GenerationAgent."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.Generation import GenerationAgent, GenerationStatus
from app.workflows.rag.state import (
    RAGWorkflowState,
    prior_conversation_messages,
)


GenerationEventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def create_generation_node(
    agent: GenerationAgent,
    *,
    event_callback: GenerationEventCallback | None = None,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a generation node using thread history and cross-thread memories."""

    async def generation_node(state: RAGWorkflowState) -> dict[str, Any]:
        documents = state.get("context_documents") or state.get("retrieved_documents") or []
        history = prior_conversation_messages(state)
        memories = state.get("long_term_memories") or []
        status = (
            GenerationStatus.ANSWERED
            if documents
            else GenerationStatus.INSUFFICIENT_EVIDENCE
        )
        generation_args: dict[str, Any] = {
            "current_query": state["query"],
            "retrieved_documents": documents,
            "conversation_history": history,
            "status": status,
        }
        # Keep compatibility with injected test/custom agents that implement
        # the pre-memory interface when no memory context is available.
        if memories:
            generation_args["long_term_memories"] = memories

        if event_callback is None:
            output = await agent.agenerate(**generation_args)
        else:
            output = None
            async for event in agent.astream_generate(**generation_args):
                if event.event_type.value == "content_delta":
                    callback_result = event_callback(
                        {
                            "type": "delta",
                            "segment_index": event.segment_index,
                            "delta": event.delta or "",
                        }
                    )
                    if hasattr(callback_result, "__await__"):
                        await callback_result
                elif event.event_type.value == "completed":
                    output = event.output
            if output is None:
                raise RuntimeError("Streaming generation ended without a validated output.")
        return {"generation_output": output}

    return generation_node
