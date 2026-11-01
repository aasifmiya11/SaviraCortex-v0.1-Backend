
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from app.services.document_indexing import (
    DocumentIndexingService,
    IndexingError,
)


@pytest.fixture
def pages():
    return [
        Document(
            page_content="Employee leave policy. " * 100,
            metadata={
                "page": 1,
                "ocr_used": False,
                "extraction_method": "pymupdf",
            },
        ),
        Document(
            page_content="Annual leave entitlement. " * 100,
            metadata={
                "page": 2,
                "ocr_used": True,
                "extraction_method": "easyocr",
            },
        ),
    ]


@pytest.fixture
def dependencies():
    splitter = MagicMock()
    qdrant = MagicMock()
    bm25 = MagicMock()

    def split_documents(documents):
        return [
            Document(
                page_content=document.page_content,
                metadata=dict(document.metadata),
            )
            for document in documents
        ]

    splitter.split_documents.side_effect = split_documents

    qdrant.add_documents.side_effect = (
        lambda documents, ids: ids
    )

    bm25.add_documents.side_effect = (
        lambda documents: [
            f"bm25-{index}"
            for index, _ in enumerate(documents)
        ]
    )

    return splitter, qdrant, bm25


def test_successful_indexing(pages, dependencies):
    splitter, qdrant, bm25 = dependencies

    service = DocumentIndexingService(
        text_splitter=splitter,
        qdrant_store=qdrant,
        bm25_store=bm25,
    )

    result = service.index_document_version(
        page_documents=pages,
        document_id="document-1",
        document_version_id="version-1",
        version_number=1,
        source_filename="policy.pdf",
    )

    assert result.page_count == 2
    assert result.ocr_page_count == 1
    assert result.chunk_count == 2
    assert len(result.qdrant_point_ids) == 2
    assert len(result.bm25_chunk_ids) == 2
    assert result.status == "completed"

    qdrant.add_documents.assert_called_once()
    bm25.add_documents.assert_called_once()

    indexed_chunks = bm25.add_documents.call_args.args[0]

    for index, chunk in enumerate(indexed_chunks):
        assert chunk.metadata["document_id"] == "document-1"
        assert chunk.metadata["document_version_id"] == "version-1"
        assert chunk.metadata["version_number"] == 1
        assert chunk.metadata["chunk_index"] == index
        assert chunk.metadata["status"] == "pending"


def test_qdrant_failure_triggers_cleanup(pages, dependencies):
    splitter, qdrant, bm25 = dependencies

    qdrant.add_documents.side_effect = RuntimeError(
        "Qdrant unavailable"
    )

    service = DocumentIndexingService(
        text_splitter=splitter,
        qdrant_store=qdrant,
        bm25_store=bm25,
    )

    with pytest.raises(IndexingError):
        service.index_document_version(
            page_documents=pages,
            document_id="document-1",
            document_version_id="version-1",
            version_number=1,
            source_filename="policy.pdf",
        )

    qdrant.delete_points.assert_called_once()
    bm25.delete_version.assert_called_once_with("version-1")


def test_bm25_failure_triggers_cleanup(pages, dependencies):
    splitter, qdrant, bm25 = dependencies

    bm25.add_documents.side_effect = RuntimeError(
        "SQLite write failed"
    )

    service = DocumentIndexingService(
        text_splitter=splitter,
        qdrant_store=qdrant,
        bm25_store=bm25,
    )

    with pytest.raises(IndexingError):
        service.index_document_version(
            page_documents=pages,
            document_id="document-1",
            document_version_id="version-1",
            version_number=1,
            source_filename="policy.pdf",
        )

    qdrant.delete_points.assert_called_once()
    bm25.delete_version.assert_called_once_with("version-1")


def test_empty_page_list_is_rejected(dependencies):
    splitter, qdrant, bm25 = dependencies

    service = DocumentIndexingService(
        text_splitter=splitter,
        qdrant_store=qdrant,
        bm25_store=bm25,
    )

    with pytest.raises(ValueError):
        service.index_document_version(
            page_documents=[],
            document_id="document-1",
            document_version_id="version-1",
            version_number=1,
            source_filename="policy.pdf",
        )


def test_invalid_version_number_is_rejected(pages, dependencies):
    splitter, qdrant, bm25 = dependencies

    service = DocumentIndexingService(
        text_splitter=splitter,
        qdrant_store=qdrant,
        bm25_store=bm25,
    )

    with pytest.raises(ValueError):
        service.index_document_version(
            page_documents=pages,
            document_id="document-1",
            document_version_id="version-1",
            version_number=0,
            source_filename="policy.pdf",
        )
