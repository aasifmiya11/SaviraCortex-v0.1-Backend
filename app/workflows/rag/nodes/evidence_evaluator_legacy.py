"""LangGraph Evidence Evaluator node backed by EvidenceEvaluatorAgent."""

from collections.abc import Callable
from typing import Any

from app.agents.Evidence_evaluator_legacy import EvidenceEvaluatorAgent
from app.workflows.rag.state import RAGWorkflowState


def create_evidence_evaluator_node(
    evaluator: EvidenceEvaluatorAgent,
) -> Callable[[RAGWorkflowState], Any]:
    """Create an evaluator node using an application-configured agent."""

    async def evidence_evaluator_node(
        state: RAGWorkflowState,
    ) -> dict[str, Any]:
        evaluation = await evaluator.aevaluate(
            current_query=state["query"],
            retrieved_documents=(
                state.get("context_documents")
                if state.get("context_documents") is not None
                else state.get("retrieved_documents") or []
            ),
            conversation_history=state.get("context"),
        )

        return {
            "is_sufficient": evaluation.is_sufficient,
            "missing_information": evaluation.missing_information,
            "retry": not evaluation.is_sufficient,
        }

    return evidence_evaluator_node
