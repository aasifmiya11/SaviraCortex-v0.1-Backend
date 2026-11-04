import pytest

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
async def test_first_retrieval_uses_original_query_without_exclusions():
    selected = [{"chunk_id": "doc-a:0", "page_content": "Evidence A"}]
    orchestrator = FakeRetrievalOrchestrator(selected)
    node = create_retriever_node(orchestrator)

    updates = await node({
        "query": "Original question",
        "organization_id": "organization",
        "user_id": "user",
    })

    assert orchestrator.received["current_query"] == "Original question"
    assert orchestrator.received["exclude"] is False
    assert orchestrator.received["excluded_chunk_ids"] is None
    assert updates["retrieval_attempt"] == 1
    assert updates["retrieved_documents"] == selected
    assert updates["excluded_chunk_ids"] == ["doc-a:0"]
    assert updates["retry"] is False


@pytest.mark.asyncio
async def test_retry_excludes_prior_chunks_and_accumulates_unique_evidence():
    previous = [
        {"chunk_id": "doc-a:0", "page_content": "Evidence A"},
        {"chunk_id": "doc-b:0", "page_content": "Evidence B"},
    ]
    newly_retrieved = [
        {"chunk_id": "doc-a:0", "page_content": "Duplicate A"},
        {"chunk_id": "doc-c:0", "page_content": "Evidence C"},
    ]
    orchestrator = FakeRetrievalOrchestrator(newly_retrieved)
    node = create_retriever_node(orchestrator)

    updates = await node({
        "query": "Original question",
        "organization_id": "organization",
        "user_id": "user",
        "retrieval_attempt": 1,
        "retrieved_documents": previous,
        "rewritten_query": "Find the missing requirement",
        "hypothetical_answer": "Hypothetical retrieval guidance",
        "retrieval_diagnostics": {
            "total_attempts": 1,
            "attempts": [{"attempt": 1}],
        },
    })

    assert orchestrator.received["exclude"] is True
    assert orchestrator.received["excluded_chunk_ids"] == ["doc-a:0", "doc-b:0"]
    assert "Original question" in orchestrator.received["current_query"]
    assert "Find the missing requirement" in orchestrator.received["current_query"]
    assert [item["chunk_id"] for item in updates["retrieved_documents"]] == [
        "doc-a:0",
        "doc-b:0",
        "doc-c:0",
    ]
    assert updates["retrieval_attempt"] == 2
    assert updates["excluded_chunk_ids"] == ["doc-a:0", "doc-b:0", "doc-c:0"]
    assert updates["retrieval_diagnostics"]["total_attempts"] == 2
    assert len(updates["retrieval_diagnostics"]["attempts"]) == 2
    assert updates["retry"] is False
