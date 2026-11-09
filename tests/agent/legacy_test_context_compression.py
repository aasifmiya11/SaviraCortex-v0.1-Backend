import pytest
from langchain_core.runnables import RunnableLambda

from app.agents.Context_compression_legacy import (
    ContextCompressionAgent,
    ContextCompressionConfig,
    ContextCompressionError,
    ContextCompressionOutput,
)


def make_agent(result, threshold=100):
    agent = ContextCompressionAgent(
        config=ContextCompressionConfig(token_threshold=threshold),
        model=RunnableLambda(lambda _: "{}"),
    )
    agent.chain = RunnableLambda(lambda _: result)
    return agent


def test_compression_preserves_one_to_one_order_and_metadata():
    documents = [
        {
            "chunk_id": "doc-a:0",
            "page_content": "The annual leave allowance is twenty days.",
            "metadata": {"document_id": "doc-a", "page": 2, "tag": "A"},
        },
        {
            "chunk_id": "doc-b:1",
            "page_content": "Requests require manager approval.",
            "metadata": {"document_id": "doc-b", "page": 8, "tag": "B"},
        },
    ]
    agent = make_agent(
        ContextCompressionOutput(
            documents=[
                {"index": 1, "compressed_content": "Annual leave: 20 days."},
                {"index": 2, "compressed_content": "Manager approval is required."},
            ]
        )
    )

    result = agent.compress("What is annual leave?", documents)

    assert len(result) == len(documents) == 2
    assert [item["chunk_id"] for item in result] == ["doc-a:0", "doc-b:1"]
    assert result[0]["metadata"] is documents[0]["metadata"]
    assert result[1]["metadata"] is documents[1]["metadata"]
    assert result[0]["page_content"] == "Annual leave: 20 days."
    assert result[1]["page_content"] == "Manager approval is required."
    assert documents[0]["page_content"] == "The annual leave allowance is twenty days."


def test_compression_rejects_missing_or_reordered_document_indexes():
    documents = [
        {"page_content": "First source."},
        {"page_content": "Second source."},
    ]
    agent = make_agent(
        ContextCompressionOutput(
            documents=[{"index": 2, "compressed_content": "Second."}]
        )
    )

    with pytest.raises(ContextCompressionError, match="exactly one result"):
        agent.compress("Question?", documents)


def test_threshold_estimate_controls_compression():
    agent = make_agent(
        ContextCompressionOutput(
            documents=[{"index": 1, "compressed_content": "Short text."}]
        ),
        threshold=10,
    )
    documents = [{"page_content": "x" * 80}]

    assert agent.estimate_token_count("Q?", documents) > 10
    assert agent.should_compress("Q?", documents) is True
    assert agent.should_compress("Q?", [{"page_content": "x"}]) is False


def test_prompt_contains_query_and_all_ordered_documents_without_metadata():
    agent = make_agent(
        ContextCompressionOutput(
            documents=[{"index": 1, "compressed_content": "Compressed."}]
        )
    )
    documents = [
        {
            "page_content": "Annual leave is twenty days.",
            "metadata": {"document_id": "private-id"},
        }
    ]
    payload = {
        "query_json": '"How much annual leave?"',
        "documents_json": '[{"index": 1, "content": "Annual leave is twenty days."}]',
    }
    rendered = agent.prompt.invoke(payload).to_string()

    assert "How much annual leave?" in rendered
    assert "Annual leave is twenty days." in rendered
    assert "private-id" not in rendered


def test_config_rejects_invalid_threshold():
    with pytest.raises(ValueError):
        ContextCompressionConfig(token_threshold=0)


def test_compression_rejects_non_string_content():
    agent = make_agent(
        ContextCompressionOutput(
            documents=[{"index": 1, "compressed_content": "Compressed."}]
        )
    )
    with pytest.raises(ValueError, match="page_content"):
        agent.compress("Question?", [{"page_content": None}])


@pytest.mark.asyncio
async def test_async_compression_returns_one_result_per_document():
    documents = [
        {"chunk_id": "a:0", "page_content": "First source.", "metadata": {"page": 1}},
        {"chunk_id": "b:0", "page_content": "Second source.", "metadata": {"page": 2}},
    ]
    expected = ContextCompressionOutput(
        documents=[
            {"index": 1, "compressed_content": "First."},
            {"index": 2, "compressed_content": "Second."},
        ]
    )
    agent = make_agent(expected)

    result = await agent.acompress("Question?", documents)

    assert [item["page_content"] for item in result] == ["First.", "Second."]
    assert [item["chunk_id"] for item in result] == ["a:0", "b:0"]
