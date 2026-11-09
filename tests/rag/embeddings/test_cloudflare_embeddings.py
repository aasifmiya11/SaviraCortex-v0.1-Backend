from __future__ import annotations

from app.rag.embeddings.cloudflare_embeddings import CloudflareEmbeddingClient


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


def test_cloudflare_embedding_client_uses_gateway_route_and_restores_order():
    from app.rag.embeddings.cloudflare_embeddings import CloudflareEmbeddingClient

    session = FakeSession([{"data": [_item(1, 2.0), _item(0, 1.0)]}])
    client = CloudflareEmbeddingClient(
        api_key="gateway-key",
        base_url="http://gateway/v1",
        session=session,
        batch_size=8,
    )
    client.dimensions = 3

    vectors = client.embed_documents(["first passage", "second passage"])

    assert vectors == [[1.0, 1.1, 1.2], [2.0, 2.1, 2.2]]
    url, request = session.calls[0]
    assert url == "http://gateway/v1/cloudflare/embeddings"
    assert request["headers"]["Authorization"] == "Bearer gateway-key"
    assert request["json"] == {"input": ["first passage", "second passage"]}


def test_cloudflare_embedding_client_uses_same_adapter_for_queries():
    from app.rag.embeddings.cloudflare_embeddings import CloudflareEmbeddingClient

    session = FakeSession([{"data": [_item(0, 0.5)]}])
    client = CloudflareEmbeddingClient(api_key="gateway-key", session=session)
    client.dimensions = 3

    assert client.embed_query("search this") == [0.5, 0.6, 0.7]
    assert session.calls[0][1]["json"]["input"] == ["search this"]
