import pytest
from langchain_core.documents import Document

from app.rag.retrieval.qdrant_bm25 import QdrantBM25Retriever


class FakeQdrantClient:
    def __init__(self):
        self.received = None

    def bm25_search_with_score(self, **kwargs):
        self.received = kwargs
        return [(Document(page_content="matched"), 0.75)]


class OrganizationScopedFakeQdrantClient(FakeQdrantClient):
    def __init__(self):
        super().__init__()
        self.documents = {
            "org-a": [(
                Document(
                    page_content="same text",
                    metadata={"organization_id": "org-a"},
                ),
                0.8,
            )],
            "org-b": [(
                Document(
                    page_content="same text",
                    metadata={"organization_id": "org-b"},
                ),
                0.8,
            )],
        }

    def bm25_search_with_score(self, **kwargs):
        self.received = kwargs
        organization_id = next(
            condition.match.value
            for condition in kwargs["query_filter"].must
            if condition.key == "metadata.organization_id"
        )
        return self.documents[organization_id]


def get_filter_conditions(query_filter):
    return {
        condition.key: condition.match.value
        for condition in query_filter.must
    }


def test_bm25_search_requires_organization_id():
    retriever = QdrantBM25Retriever(FakeQdrantClient())

    with pytest.raises(ValueError, match="organization_id cannot be empty"):
        retriever.search("retrieval", organization_id=" ")


def test_bm25_search_filters_inside_qdrant():
    client = FakeQdrantClient()
    retriever = QdrantBM25Retriever(client)

    results = retriever.search(
        query="retrieval",
        organization_id="org-1",
        document_id="doc-1",
        user_id="user-1",
        status="active",
    )

    assert isinstance(results[0][0], Document)
    assert results[0][1] == 0.75
    assert get_filter_conditions(client.received["query_filter"]) == {
        "metadata.organization_id": "org-1",
        "metadata.document_id": "doc-1",
        "metadata.user_id": "user-1",
        "metadata.status": "active",
    }


def test_bm25_organization_filter_remains_when_status_is_disabled():
    client = FakeQdrantClient()
    retriever = QdrantBM25Retriever(client)

    retriever.search(
        query="retrieval",
        organization_id="org-1",
        status=None,
    )

    assert get_filter_conditions(client.received["query_filter"]) == {
        "metadata.organization_id": "org-1",
    }


def test_bm25_search_does_not_cross_organization_boundary():
    client = OrganizationScopedFakeQdrantClient()
    retriever = QdrantBM25Retriever(client)

    organization_a_results = retriever.search(
        "same text",
        organization_id="org-a",
    )
    organization_b_results = retriever.search(
        "same text",
        organization_id="org-b",
    )

    assert organization_a_results[0][0].page_content == "same text"
    assert organization_b_results[0][0].page_content == "same text"
    assert organization_a_results[0][0].metadata["organization_id"] == "org-a"
    assert organization_b_results[0][0].metadata["organization_id"] == "org-b"
    assert client.received["query_filter"].must[0].key == (
        "metadata.organization_id"
    )
