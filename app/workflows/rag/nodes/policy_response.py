from typing import Any

from app.agents.Generation.schemas import (
    AnswerSegment,
    GenerationOutput,
    GenerationStatus,
)
from app.workflows.rag.state import RAGWorkflowState
from app.guardrails.runtime_schemas import resolve_effective_policy


def policy_response_node(state: RAGWorkflowState) -> dict[str, Any]:
    """Return the tenant-configured gentle response for an off-topic query."""
    policy = resolve_effective_policy(state.get("effective_guardrail_policy") or {})
    blocked = state.get("input_guardrail_blocked") is True
    message = (
        state.get("input_guardrail_message")
        or "I cannot help with that request because it conflicts with the organization guardrails."
        if blocked else policy.off_topic_message
    )
    output = GenerationOutput(
        status=GenerationStatus.PARTIAL,
        segments=[AnswerSegment(text=message, citations=[])],
    )
    return {
        "generation_output": output,
        "retrieved_documents": [],
        "guardrail_decision": "blocked" if blocked else "redirected",
    }
