import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.workflows.rag.nodes.retriever import create_retriever_node


class FakeRetrievalOrchestrator:
    def __init__(self, selected_candidates):
        self.selected_candidates = selected_candidates
        self.received = None

    async def retrieve(self, **kwargs):
        self.received = kwargs
        return {
            "selected_candidates": self.selected_candidates,
            "selected_count": len(self.selected_candidates),
            "eligible_count": len(self.selected_candidates),
            "fused_count": len(self.selected_candidates),
            "reranked_count": len(self.selected_candidates),
            "branch_count": 1,
            "expansion": {"rounds_performed": 0},
        }


@pytest.mark.asyncio
async def test_retriever_receives_restored_conversation_history():
    selected = [{"chunk_id": "doc-a:0", "page_content": "Evidence A"}]
    orchestrator = FakeRetrievalOrchestrator(selected)
    node = create_retriever_node(orchestrator)
    history = [
        HumanMessage(id="prior-user", content="What does the leave policy say?"),
        AIMessage(id="prior-assistant", content="It describes annual leave."),
    ]

    updates = await node({
        "query": "How many days?",
        "organization_id": "organization",
        "user_id": "user",
        "request_id": "current-request",
        "messages": [
            *history,
            HumanMessage(id="current-request", content="How many days?"),
        ],
    })

    assert orchestrator.received["current_query"] == "How many days?"
    assert orchestrator.received["conversation_history"] == history
    assert updates["retrieval_attempt"] == 1
    assert updates["retrieved_documents"] == selected
    assert updates["retrieval_trace"]["selected_count"] == 1


@pytest.mark.asyncio
async def test_retriever_passes_none_when_no_prior_conversation_exists():
    orchestrator = FakeRetrievalOrchestrator([])
    node = create_retriever_node(orchestrator)

    updates = await node({
        "query": "Original question",
        "organization_id": "organization",
        "user_id": "user",
    })

    assert orchestrator.received["conversation_history"] is None
    assert updates["retrieval_attempt"] == 1
    assert updates["retrieved_documents"] == []


@pytest.mark.asyncio
async def test_retriever_fails_closed_when_candidate_generation_fails():
    class FailingOrchestrator(FakeRetrievalOrchestrator):
        async def retrieve(self, **kwargs):
            return {"candidate_generation_error": "backend failure"}

    node = create_retriever_node(FailingOrchestrator([]))

    with pytest.raises(Exception, match="Authorized document candidate generation failed"):
        await node({
            "query": "Original question",
            "organization_id": "organization",
            "user_id": "user",
        })


@pytest.mark.asyncio
async def test_retrieval_guardrails_filter_ingestion_flagged_chunks_by_default():
    flagged = {
        "chunk_id": "doc-injected:0",
        "page_content": "Injected instructions",
        "metadata": {"prompt_injection_flagged": True},
    }
    safe = {
        "chunk_id": "doc-safe:0",
        "page_content": "Approved evidence",
        "metadata": {"prompt_injection_flagged": False},
    }
    node = create_retriever_node(FakeRetrievalOrchestrator([flagged, safe]))

    updates = await node({
        "query": "Find policy",
        "organization_id": "organization",
        "user_id": "user",
    })

    assert updates["retrieved_documents"] == [safe]
    assert updates["retrieval_trace"]["selected_count"] == 1


@pytest.mark.asyncio
async def test_disabling_retrieval_guardrails_bypasses_flagged_chunk_filter():
    flagged = {
        "chunk_id": "doc-injected:0",
        "page_content": "Injected instructions",
        "metadata": {"prompt_injection_flagged": True},
    }
    node = create_retriever_node(FakeRetrievalOrchestrator([flagged]))

    updates = await node({
        "query": "Find policy",
        "organization_id": "organization",
        "user_id": "user",
        "effective_guardrail_policy": {"retrieval_guardrails_enabled": False},
    })

    assert updates["retrieved_documents"] == [flagged]
