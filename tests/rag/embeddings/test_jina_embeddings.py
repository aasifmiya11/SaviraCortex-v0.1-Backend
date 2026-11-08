from __future__ import annotations

import pytest

from app.rag.embeddings.jina_embeddings import JinaEmbeddingClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.responses.pop(0))


def _item(index, value):
    return {"index": index, "embedding": [value, value + 0.1, value + 0.2]}


def test_embed_documents_sends_passage_task_and_restores_response_order():
    session = FakeSession([{"data": [_item(1, 2.0), _item(0, 1.0)]}])
    client = JinaEmbeddingClient(
        api_key="test-key", model_name="test-model", session=session, batch_size=8
    )
    client.dimensions = 3

    vectors = client.embed_documents(["first passage", "second passage"])

    assert vectors == [[1.0, 1.1, 1.2], [2.0, 2.1, 2.2]]
    url, request = session.calls[0]
    assert url.endswith("/embeddings")
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"]["task"] == "retrieval.passage"
    assert request["json"]["input"] == ["first passage", "second passage"]
    assert request["json"]["dimensions"] == 3


def test_embed_query_uses_query_task():
    session = FakeSession([{"data": [_item(0, 0.5)]}])
    client = JinaEmbeddingClient(api_key="test-key", session=session)
    client.dimensions = 3

    assert client.embed_query("search this") == [0.5, 0.6, 0.7]
    assert session.calls[0][1]["json"]["task"] == "retrieval.query"


def test_embedding_batches_large_document_lists():
    session = FakeSession([
        {"data": [_item(0, 1.0), _item(1, 2.0)]},
        {"data": [_item(0, 3.0)]},
    ])
    client = JinaEmbeddingClient(
        api_key="test-key", session=session, batch_size=2
    )
    client.dimensions = 3

    vectors = client.embed_documents(["one", "two", "three"])

    assert len(vectors) == 3
    assert len(session.calls) == 2
    assert [call[1]["json"]["input"] for call in session.calls] == [
        ["one", "two"], ["three"]
    ]


def test_embedding_rejects_empty_input_and_missing_api_key():
    client = JinaEmbeddingClient(api_key="", session=FakeSession([]))

    with pytest.raises(ValueError, match="non-empty"):
        client.embed_documents([" "])
    with pytest.raises(RuntimeError, match="JINA_API_KEY"):
        client.embed_query("query")


def test_embedding_rejects_wrong_vector_dimension():
    session = FakeSession([{"data": [_item(0, 1.0)]}])
    client = JinaEmbeddingClient(api_key="test-key", session=session)
    client.dimensions = 4

    with pytest.raises(RuntimeError, match="expected 4"):
        client.embed_query("query")


def test_embedding_rejects_duplicate_response_indices():
    session = FakeSession([{"data": [_item(0, 1.0), _item(0, 2.0)]}])
    client = JinaEmbeddingClient(api_key="test-key", session=session)
    client.dimensions = 3

    with pytest.raises(RuntimeError, match="duplicate"):
        client.embed_documents(["first", "second"])


def test_embed_texts_compatibility_helper_skips_blank_values():
    session = FakeSession([{"data": [_item(0, 1.0)]}])
    client = JinaEmbeddingClient(api_key="test-key", session=session)
    client.dimensions = 3

    assert client.embed_texts(["first", " ", ""]) == [[1.0, 1.1, 1.2]]
    assert session.calls[0][1]["json"]["input"] == ["first"]
