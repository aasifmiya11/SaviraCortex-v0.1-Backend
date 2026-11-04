import pytest

from app.agents.Evidence_evaluator import EvidenceEvaluation
from app.workflows.rag.nodes.evidence_evaluator import (
    create_evidence_evaluator_node,
)


class FakeEvidenceEvaluator:
    def __init__(self, result):
        self.result = result
        self.received = None

    async def aevaluate(
        self,
        current_query,
        retrieved_documents,
        conversation_history=None,
    ):
        self.received = {
            "current_query": current_query,
            "retrieved_documents": retrieved_documents,
            "conversation_history": conversation_history,
        }
        return self.result


@pytest.mark.asyncio
async def test_evidence_evaluator_node_passes_query_context_and_documents():
    documents = [
        {"chunk_id": "chunk-1", "page_content": "Annual leave is 20 days."}
    ]
    context = []
    evaluator = FakeEvidenceEvaluator(
        EvidenceEvaluation(
            is_sufficient=False,
            missing_information=["The leave approval process."],
        )
    )
    node = create_evidence_evaluator_node(evaluator)

    updates = await node(
        {
            "query": "How many leave days and how is leave approved?",
            "organization_id": "org-id",
            "user_id": "user-id",
            "context": context,
            "retrieved_documents": documents,
        }
    )

    assert evaluator.received == {
        "current_query": "How many leave days and how is leave approved?",
        "retrieved_documents": documents,
        "conversation_history": context,
    }
    assert updates == {
        "is_sufficient": False,
        "missing_information": ["The leave approval process."],
        "retry": True,
    }


@pytest.mark.asyncio
async def test_sufficient_evidence_disables_retry():
    evaluator = FakeEvidenceEvaluator(
        EvidenceEvaluation(
            is_sufficient=True,
            missing_information=[],
        )
    )
    node = create_evidence_evaluator_node(evaluator)

    updates = await node(
        {
            "query": "How many annual leave days?",
            "organization_id": "org-id",
            "user_id": "user-id",
        }
    )

    assert updates == {
        "is_sufficient": True,
        "missing_information": [],
        "retry": False,
    }


@pytest.mark.asyncio
async def test_evaluator_node_defaults_missing_documents_and_context_to_empty():
    evaluator = FakeEvidenceEvaluator(
        EvidenceEvaluation(
            is_sufficient=False,
            missing_information=["Relevant company-document evidence."],
        )
    )
    node = create_evidence_evaluator_node(evaluator)

    await node(
        {
            "query": "What is the leave policy?",
            "organization_id": "org-id",
            "user_id": "user-id",
        }
    )

    assert evaluator.received["retrieved_documents"] == []
    assert evaluator.received["conversation_history"] is None
