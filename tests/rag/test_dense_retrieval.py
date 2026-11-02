
import pytest
from langchain_core.documents import Document

from app.rag.retrieval.dense import DenseRetriever
from app.rag.vector_stores.qdrant import QdrantVectorStoreClient


class FakeQdrantClient:
    def __init__(self):
        self.received = None

    def similarity_search_with_score(self, **kwargs):
        self.received = kwargs
        return []


class OrganizationScopedFakeQdrantClient(FakeQdrantClient):
    def __init__(self):
        super().__init__()
        self.documents = {
            "org-a": [(
                Document(
                    page_content="same text",
                    metadata={"organization_id": "org-a"},
                ),
                0.9,
            )],
            "org-b": [(
                Document(
                    page_content="same text",
                    metadata={"organization_id": "org-b"},
                ),
                0.9,
            )],
        }

    def similarity_search_with_score(self, **kwargs):
        self.received = kwargs
        organization_id = next(
            condition.match.value
            for condition in kwargs["query_filter"].must
            if condition.key == "metadata.organization_id"
        )
        return self.documents[organization_id]


def get_filter_conditions(query_filter):
    if query_filter is None:
        return {}

    return {
        condition.key: condition.match.value
        for condition in query_filter.must
    }


def test_default_dense_search_filters_active_chunks():
    retriever = DenseRetriever()
    fake_client = FakeQdrantClient()
    retriever.vector_store = fake_client

    retriever.search("machine learning", organization_id="org-1")

    assert fake_client.received["query"] == "machine learning"
    assert fake_client.received["k"] == 20

    conditions = get_filter_conditions(
        fake_client.received["query_filter"]
    )

    assert conditions == {
        "metadata.organization_id": "org-1",
        "metadata.status": "active",
    }


def test_dense_search_filters_by_document_and_user():
    retriever = DenseRetriever()
    fake_client = FakeQdrantClient()
    retriever.vector_store = fake_client

    retriever.search(
        query="machine learning",
        organization_id="org-1",
        k=10,
        document_id="doc-123",
        user_id="user-456",
    )

    conditions = get_filter_conditions(
        fake_client.received["query_filter"]
    )

    assert conditions == {
        "metadata.organization_id": "org-1",
        "metadata.document_id": "doc-123",
        "metadata.user_id": "user-456",
        "metadata.status": "active",
    }


def test_dense_search_supports_explicit_pending_status():
    retriever = DenseRetriever()
    fake_client = FakeQdrantClient()
    retriever.vector_store = fake_client

    retriever.search(
        query="machine learning",
        organization_id="org-1",
        status="pending",
    )

    conditions = get_filter_conditions(
        fake_client.received["query_filter"]
    )

    assert conditions == {
        "metadata.organization_id": "org-1",
        "metadata.status": "pending",
    }


def test_dense_search_status_none_disables_lifecycle_filter():
    retriever = DenseRetriever()
    fake_client = FakeQdrantClient()
    retriever.vector_store = fake_client

    retriever.search(
        query="machine learning",
        organization_id="org-1",
        status=None,
    )

    assert get_filter_conditions(
        fake_client.received["query_filter"]
    ) == {"metadata.organization_id": "org-1"}


def test_dense_search_status_none_preserves_other_filters():
    retriever = DenseRetriever()
    fake_client = FakeQdrantClient()
    retriever.vector_store = fake_client

    retriever.search(
        query="machine learning",
        organization_id="org-1",
        document_id="doc-123",
        user_id="user-456",
        status=None,
    )

    conditions = get_filter_conditions(
        fake_client.received["query_filter"]
    )

    assert conditions == {
        "metadata.organization_id": "org-1",
        "metadata.document_id": "doc-123",
        "metadata.user_id": "user-456",
    }


def test_dense_search_rejects_empty_query():
    retriever = DenseRetriever()

    with pytest.raises(ValueError, match="query cannot be empty"):
        retriever.search("   ", organization_id="org-1")


def test_dense_search_requires_organization_id():
    retriever = DenseRetriever()

    with pytest.raises(ValueError, match="organization_id cannot be empty"):
        retriever.search("machine learning", organization_id=" ")


def test_dense_search_does_not_cross_organization_boundary():
    client = OrganizationScopedFakeQdrantClient()
    retriever = DenseRetriever(client)

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


def test_dense_search_rejects_invalid_k():
    retriever = DenseRetriever()

    with pytest.raises(ValueError, match="k must be at least 1"):
        retriever.search(
            "machine learning",
            organization_id="org-1",
            k=0,
        )


def test_dense_search_rejects_empty_status():
    retriever = DenseRetriever()

    with pytest.raises(ValueError, match="status cannot be empty"):
        retriever.search(
            "machine learning",
            organization_id="org-1",
            status=" ",
        )


def test_qdrant_wrapper_forwards_query_filter():
    class FakeVectorStore:
        def __init__(self):
            self.received = None

        def similarity_search_with_score(self, **kwargs):
            self.received = kwargs
            return []

    wrapper = QdrantVectorStoreClient.__new__(
        QdrantVectorStoreClient
    )
    fake_store = FakeVectorStore()
    wrapper.vector_store = fake_store

    query_filter = object()

    wrapper.similarity_search_with_score(
        query="machine learning",
        k=15,
        query_filter=query_filter,
    )

    assert fake_store.received == {
        "query": "machine learning",
        "k": 15,
        "query_filter": query_filter,
    }
