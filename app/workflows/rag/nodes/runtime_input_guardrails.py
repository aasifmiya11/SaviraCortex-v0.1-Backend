from __future__ import annotations

from typing import Any

from app.guardrails.runtime_schemas import resolve_effective_policy
from app.guardrails.runtime_service import RuntimeGuardrailService
from app.workflows.rag.state import RAGWorkflowState, prior_conversation_messages


_guardrail_service = RuntimeGuardrailService()


async def runtime_input_guardrails_node(state: RAGWorkflowState) -> dict[str, Any]:
    """Run semantic input checks and tenant topicality before retrieval."""
    if state.get("is_valid") is not True:
        return {
            "input_guardrail_findings": [],
            "input_guardrail_blocked": False,
            "input_guardrail_message": None,
            "topicality_decision": "not_configured",
            "topicality_similarity": None,
        }
    raw_policy = state.get("effective_guardrail_policy") or {}
    policy = resolve_effective_policy(raw_policy)
    result = await _guardrail_service.inspect_input(
        query=state["query"],
        history=prior_conversation_messages(state),
        policy=policy,
    )
    topicality = result["topicality"]["decision"]
    blocked = bool(result["blocked_findings"]) or topicality == "uncertain"
    return {
        "input_guardrail_findings": result["findings"],
        "input_guardrail_blocked": blocked,
        "input_guardrail_message": (
            "I can't help with that request. Please rephrase it in a way that follows the organization's usage policies."
            if blocked else None
        ),
        "topicality_decision": topicality,
        "topicality_similarity": result["topicality"].get("similarity"),
    }
