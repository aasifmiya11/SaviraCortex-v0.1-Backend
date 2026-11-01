
from langchain_core.documents import Document

from app.rag.vector_stores.bm25 import BM25VectorStoreClient
from app.rag.retrieval.bm25 import BM25Retriever


def make_document(
    content: str,
    *,
    document_id: str = "doc-1",
    version_id: str = "version-1",
    chunk_index: int = 0,
    user_id: str = "user-1",
    status: str = "active",
) -> Document:
    return Document(
        page_content=content,
        metadata={
            "document_id": document_id,
            "document_version_id": version_id,
            "chunk_index": chunk_index,
            "user_id": user_id,
            "status": status,
        },
    )


def create_store(tmp_path):
    return BM25VectorStoreClient(
        db_path=str(tmp_path / "bm25_test.sqlite3")
    )


def test_default_search_returns_only_active_chunks(tmp_path):
    store = create_store(tmp_path)

    store.add_documents([
        make_document("retrieval active chunk", status="active"),
        make_document(
            "retrieval pending chunk",
            version_id="version-2",
            status="pending",
        ),
        make_document(
            "retrieval superseded chunk",
            version_id="version-3",
            status="superseded",
        ),
        make_document(
            "retrieval archived chunk",
            version_id="version-4",
            status="archived",
        ),
    ])

    results = store.similarity_search_with_score("retrieval")

    assert len(results) == 1
    assert results[0][0].metadata["status"] == "active"


def test_explicit_pending_status_returns_pending_chunks(tmp_path):
    store = create_store(tmp_path)

    store.add_documents([
        make_document("retrieval active chunk", status="active"),
        make_document(
            "retrieval pending chunk",
            version_id="version-2",
            status="pending",
        ),
    ])

    results = store.similarity_search_with_score(
        query="retrieval",
        status="pending",
    )

    assert len(results) == 1
    assert results[0][0].metadata["status"] == "pending"


def test_status_none_disables_lifecycle_filter(tmp_path):
    store = create_store(tmp_path)

    statuses = ["active", "pending", "superseded", "archived"]

    store.add_documents([
        make_document(
            f"retrieval {status} chunk",
            version_id=f"version-{index}",
            status=status,
            chunk_index=index,
        )
        for index, status in enumerate(statuses)
    ])

    results = store.similarity_search_with_score(
        query="retrieval",
        status=None,
    )

    returned_statuses = {
        document.metadata["status"]
        for document, _ in results
    }

    assert returned_statuses == set(statuses)


def test_document_id_filter_is_applied(tmp_path):
    store = create_store(tmp_path)

    store.add_documents([
        make_document("retrieval first document", document_id="doc-1"),
        make_document(
            "retrieval second document",
            document_id="doc-2",
            version_id="version-2",
        ),
    ])

    results = store.similarity_search_with_score(
        query="retrieval",
        document_id="doc-2",
    )

    assert len(results) == 1
    assert results[0][0].metadata["document_id"] == "doc-2"


def test_user_id_filter_is_applied(tmp_path):
    store = create_store(tmp_path)

    store.add_documents([
        make_document("retrieval first user", user_id="user-1"),
        make_document(
            "retrieval second user",
            user_id="user-2",
            version_id="version-2",
        ),
    ])

    results = store.similarity_search_with_score(
        query="retrieval",
        user_id="user-2",
    )

    assert len(results) == 1
    assert results[0][0].metadata["user_id"] == "user-2"


def test_similarity_search_forwards_lifecycle_filter(tmp_path):
    store = create_store(tmp_path)

    store.add_documents([
        make_document("retrieval active chunk", status="active"),
        make_document(
            "retrieval pending chunk",
            version_id="version-2",
            status="pending",
        ),
    ])

    results = store.similarity_search(
        query="retrieval",
        status="pending",
    )

    assert len(results) == 1
    assert results[0].metadata["status"] == "pending"


def test_retriever_forwards_all_filters():
    class FakeVectorStore:
        def __init__(self):
            self.received = None

        def similarity_search_with_score(self, **kwargs):
            self.received = kwargs
            return []

    retriever = BM25Retriever()
    fake_store = FakeVectorStore()
    retriever.vector_store = fake_store

    retriever.search(
        query="retrieval",
        k=10,
        document_id="doc-1",
        user_id="user-1",
        status="pending",
    )

    assert fake_store.received == {
        "query": "retrieval",
        "k": 10,
        "document_id": "doc-1",
        "user_id": "user-1",
        "status": "pending",
    }


def test_retriever_rejects_empty_query():
    retriever = BM25Retriever()

    try:
        retriever.search("   ")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "query cannot be empty."


def test_retriever_rejects_invalid_k():
    retriever = BM25Retriever()

    try:
        retriever.search("retrieval", k=0)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "k must be at least 1."


def test_retriever_rejects_empty_status():
    retriever = BM25Retriever()

    try:
        retriever.search("retrieval", status=" ")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "status cannot be empty."
