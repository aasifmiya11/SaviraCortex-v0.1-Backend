"""LangGraph Generation node backed by GenerationAgent."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.Generation import GenerationAgent, GenerationStatus
from app.workflows.rag.state import RAGWorkflowState


GenerationEventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def create_generation_node(
    agent: GenerationAgent,
    *,
    event_callback: GenerationEventCallback | None = None,
) -> Callable[[RAGWorkflowState], Any]:
    """Create a generation node, optionally forwarding provisional text deltas.

    The final state always contains a parsed GenerationOutput. When streaming,
    only text deltas are forwarded before the complete answer has passed the
    existing citation validator in the graph's next node.
    """

    async def generation_node(state: RAGWorkflowState) -> dict[str, Any]:
        # Pass the exact Adaptive-K selection directly to GenerationAgent.
        documents = state.get("retrieved_documents") or []
        history = state.get("context")
        status = (
            GenerationStatus.ANSWERED
            if documents
            else GenerationStatus.INSUFFICIENT_EVIDENCE
        )
        if event_callback is None:
            output = await agent.agenerate(
                current_query=state["query"],
                retrieved_documents=documents,
                conversation_history=history,
                status=status,
            )
        else:
            output = None
            async for event in agent.astream_generate(
                current_query=state["query"],
                retrieved_documents=documents,
                conversation_history=history,
                status=status,
            ):
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
