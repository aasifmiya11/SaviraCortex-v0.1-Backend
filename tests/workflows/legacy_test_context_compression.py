import pytest

from app.workflows.rag.nodes.context_compression_legacy import (
    create_context_compression_node,
)


class FakeContextCompressionAgent:
    def __init__(self):
        self.received = None

    def estimate_token_count(self, query, documents):
        return len(query + "".join(item["page_content"] for item in documents))

    async def acompress(self, current_query, retrieved_documents):
        self.received = (current_query, retrieved_documents)
        result = []
        for item in retrieved_documents:
            compressed = dict(item)
            compressed["page_content"] = "compressed: " + item["page_content"][:5]
            result.append(compressed)
        return result


@pytest.mark.asyncio
async def test_node_compresses_all_documents_when_graph_routes_to_it():
    documents = [
        {"chunk_id": "a:0", "page_content": "Long original content A", "metadata": {"page": 1}},
        {"chunk_id": "b:0", "page_content": "Long original content B", "metadata": {"page": 2}},
    ]
    agent = FakeContextCompressionAgent()
    node = create_context_compression_node(agent)

    updates = await node({"query": "Question", "retrieved_documents": documents})

    assert agent.received == ("Question", documents)
    assert updates["context_compressed"] is True
    assert len(updates["context_documents"]) == 2
    assert updates["context_documents"][0]["chunk_id"] == "a:0"
    assert updates["context_documents"][1]["metadata"] == {"page": 2}
    assert documents[0]["page_content"] == "Long original content A"


@pytest.mark.asyncio
async def test_node_does_not_apply_a_second_token_threshold():
    documents = [{"chunk_id": "a:0", "page_content": "Short", "metadata": {}}]
    agent = FakeContextCompressionAgent()
    node = create_context_compression_node(agent)

    updates = await node({"query": "Q", "retrieved_documents": documents})

    assert agent.received == ("Q", documents)
    assert updates["context_compressed"] is True


@pytest.mark.asyncio
async def test_node_handles_empty_retrieval_without_model_call():
    agent = FakeContextCompressionAgent()
    node = create_context_compression_node(agent)

    updates = await node({"query": "Question", "retrieved_documents": []})

    assert updates == {
        "context_documents": [],
        "context_compressed": False,
        "context_token_estimate": 0,
    }
    assert agent.received is None
