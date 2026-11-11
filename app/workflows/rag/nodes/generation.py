"""LangGraph Generation node backed by GenerationAgent and output segment checks."""

import re
from collections.abc import Callable
from typing import Any

from app.agents.Generation import GenerationAgent, GenerationStatus
from langchain_core.messages import HumanMessage
from app.services.generation.image_attachments import hydrate_image_history
from app.guardrails.runtime_schemas import resolve_effective_policy
from app.guardrails.runtime_service import RuntimeGuardrailService
from app.workflows.rag.state import (
    RAGWorkflowState,
    prior_conversation_messages,
)

GenerationEventCallback = Callable[[dict[str, Any]], Any]
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def create_generation_node(
    agent: GenerationAgent,
    *,
    event_callback: GenerationEventCallback | None = None,
) -> Callable[[RAGWorkflowState], Any]:
    """Create generation with buffered sentence-level checks before SSE release."""

    async def generation_node(state: RAGWorkflowState) -> dict[str, Any]:
        documents = state.get("context_documents") or state.get("retrieved_documents") or []
        history = list(prior_conversation_messages(state) or [])
        request_id = str(state.get("request_id") or "")
        current_image_message = next((
            message for message in state.get("messages", [])
            if isinstance(message, HumanMessage)
            and str(getattr(message, "id", "")) == request_id
            and (getattr(message, "additional_kwargs", None) or {}).get("image_attachments")
        ), None)
        if current_image_message is not None:
            history.append(current_image_message)
        history = hydrate_image_history(history)
        memories = state.get("long_term_memories") or []
        has_image_input = any(
            isinstance(getattr(message, "content", None), list)
            and any(isinstance(block, dict) and block.get("type") == "image_url" for block in message.content)
            for message in history
        )
        status = (
            GenerationStatus.ANSWERED
            if documents or has_image_input
            else GenerationStatus.INSUFFICIENT_EVIDENCE
        )
        generation_args: dict[str, Any] = {
            "current_query": state["query"],
            "retrieved_documents": documents,
            "conversation_history": history if history else None,
            "status": status,
        }
        if memories:
            generation_args["long_term_memories"] = memories

        if event_callback is None:
            output = await agent.agenerate(**generation_args)
        else:
            output = None
            policy = resolve_effective_policy(
                state.get("effective_guardrail_policy") or {}
            )
            guardrails = RuntimeGuardrailService()
            pending = ""

            async def release_segment(segment: str) -> None:
                checked = await guardrails.inspect_stream_segment(
                    segment=segment,
                    query=state["query"],
                    history=history,
                    policy=policy,
                    evidence=documents,
                )
                callback_result = event_callback(
                    {
                        "type": "delta",
                        "segment_index": 0,
                        "delta": checked,
                    }
                )
                if hasattr(callback_result, "__await__"):
                    await callback_result

            async for event in agent.astream_generate(**generation_args):
                if event.event_type.value == "content_delta":
                    pending += event.delta or ""
                    while True:
                        boundary = _SENTENCE_BOUNDARY.search(pending)
                        if boundary:
                            segment = pending[:boundary.end()]
                            pending = pending[boundary.end():]
                            await release_segment(segment)
                            continue
                        if len(pending) > 2000:
                            split_at = pending.rfind(" ", 0, 2000)
                            if split_at > 0:
                                segment = pending[:split_at + 1]
                                pending = pending[split_at + 1:]
                                await release_segment(segment)
                        break
                elif event.event_type.value == "completed":
                    output = event.output

            if pending:
                await release_segment(pending)
            if output is None:
                raise RuntimeError("Streaming generation ended without a validated output.")

        return {"generation_output": output}

    return generation_node
