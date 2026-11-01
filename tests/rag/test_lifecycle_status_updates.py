import json
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document
from qdrant_client import models

from app.rag.vector_stores.bm25 import BM25VectorStoreClient
from app.rag.vector_stores.qdrant import QdrantVectorStoreClient


@pytest.fixture
def bm25_store(tmp_path):
    return BM25VectorStoreClient(
        db_path=str(tmp_path / "test_bm25.sqlite3")
    )


def test_bm25_updates_only_target_version(bm25_store):
    store = bm25_store

    store.add_documents([
        Document(
            page_content="target version chunk",
            metadata={
                "document_id": "doc-1",
                "document_version_id": "version-1",
                "chunk_index": 0,
                "status": "pending",
                "source": "resume.pdf",
            },
        ),
        Document(
            page_content="other version chunk",
            metadata={
                "document_id": "doc-1",
                "document_version_id": "version-2",
                "chunk_index": 0,
                "status": "active",
                "source": "resume.pdf",
            },
        ),
    ])

    updated = store.update_version_status("version-1", "active")

    assert updated == 1

    target = next(
        doc for doc in store.documents
        if doc.metadata["document_version_id"] == "version-1"
    )
    other = next(
        doc for doc in store.documents
        if doc.metadata["document_version_id"] == "version-2"
    )

    assert target.metadata["status"] == "active"
    assert target.metadata["source"] == "resume.pdf"
    assert other.metadata["status"] == "active"


def test_bm25_update_persists_to_sqlite(bm25_store):
    store = bm25_store

    store.add_documents([
        Document(
            page_content="persistent lifecycle test",
            metadata={
                "document_id": "doc-1",
                "document_version_id": "version-1",
                "chunk_index": 0,
                "status": "pending",
            },
        )
    ])

    store.update_version_status("version-1", "active")

    with store._get_connection() as conn:
        row = conn.execute(
            """
            SELECT metadata
            FROM bm25_documents
            WHERE document_version_id = ?
            """,
            ("version-1",),
        ).fetchone()

    assert json.loads(row[0])["status"] == "active"


def test_bm25_update_returns_zero_for_unknown_version(bm25_store):
    assert bm25_store.update_version_status(
        "unknown-version", "active"
    ) == 0


def test_qdrant_updates_version_status():
    store = QdrantVectorStoreClient.__new__(QdrantVectorStoreClient)
    store.collection_name = "test_collection"
    store.client = MagicMock()

    store.update_version_status("version-1", "active")

    assert store.client.set_payload.call_count == 2

    root_call = store.client.set_payload.call_args_list[0].kwargs
    nested_call = store.client.set_payload.call_args_list[1].kwargs

    assert root_call["payload"] == {"status": "active"}
    assert root_call["wait"] is True
    assert "key" not in root_call

    assert nested_call["payload"] == {"status": "active"}
    assert nested_call["key"] == "metadata"
    assert nested_call["wait"] is True

    for call in (root_call, nested_call):
        assert call["collection_name"] == "test_collection"
        selector = call["points"]
        assert isinstance(selector, models.Filter)
        assert selector.must[0].key == "metadata.document_version_id"
        assert selector.must[0].match.value == "version-1"

@pytest.mark.parametrize(
    "version_id,status",
    [
        ("", "active"),
        ("version-1", ""),
    ],
)
def test_qdrant_rejects_empty_values(version_id, status):
    store = QdrantVectorStoreClient.__new__(QdrantVectorStoreClient)
    store.collection_name = "test_collection"
    store.client = MagicMock()

    with pytest.raises(ValueError):
        store.update_version_status(version_id, status)

    store.client.set_payload.assert_not_called()