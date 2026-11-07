from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import Document, DocumentACL, DocumentVersion
from app.services.document_management import (
    DocumentDeletionError,
    DocumentDeletionService,
)


class FakeChunkStore:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.deleted_documents = []

    def delete_document(self, document_id):
        if self.error:
            raise self.error
        self.deleted_documents.append(document_id)


class FakeSummaryStore:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.deleted_documents = []

    def delete_document(self, document_id):
        if self.error:
            raise self.error
        self.deleted_documents.append(document_id)


class FakeFileStorage:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.deleted_keys = []

    def delete_file(self, storage_key):
        if self.error:
            raise self.error
        self.deleted_keys.append(storage_key)

    def delete_file_permanently(self, storage_key):
        self.delete_file(storage_key)


def create_version(db_session, document, number: int, storage_key: str, previous=None):
    version = DocumentVersion(
        document_id=document.id,
        version_number=number,
        version_label=f"v{number}",
        original_filename=f"policy-v{number}.pdf",
        storage_key=storage_key,
        file_hash=f"{number:064x}",
        content_hash=f"{number + 10:064x}",
        summary=f"Summary for version {number}",
        status="superseded" if previous else "active",
        page_count=3,
        supersedes_version_id=previous.id if previous else None,
    )
    db_session.add(version)
    db_session.flush()
    return version


def test_delete_document_removes_all_versions_files_chunks_bm25_and_summaries(
    db_session, organization_context
):
    organization = organization_context["organization"]
    owner = organization_context["owner"]
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Security policy",
        document_type="Policy",
        description="Current security policy.",
    )
    db_session.add(document)
    db_session.flush()
    first = create_version(db_session, document, 1, "org/doc/v1.pdf")
    second = create_version(db_session, document, 2, "org/doc/v2.pdf", previous=first)
    db_session.add(
        DocumentACL(
            organization_id=organization.id,
            document_id=document.id,
            principal_type="role",
            role_id=organization_context["member_role"].id,
            effect="allow",
        )
    )
    db_session.commit()

    chunks = FakeChunkStore()
    summaries = FakeSummaryStore()
    files = FakeFileStorage()
    result = DocumentDeletionService(
        chunk_store=chunks,
        summary_store=summaries,
        file_storage=files,
    ).delete_document(
        db_session,
        document_id=document.id,
        organization_id=organization.id,
    )

    assert result.document_id == document.id
    assert result.deleted_versions == 2
    assert result.deleted_files == 2
    assert chunks.deleted_documents == [document.id]
    assert summaries.deleted_documents == [document.id]
    assert files.deleted_keys == ["org/doc/v1.pdf", "org/doc/v2.pdf"]
    assert db_session.get(Document, document.id) is None
    assert db_session.query(DocumentVersion).filter_by(document_id=document.id).count() == 0
    assert db_session.query(DocumentACL).filter_by(document_id=document.id).count() == 0


def test_delete_document_preserves_database_and_files_when_qdrant_cleanup_fails(
    db_session, organization_context
):
    organization = organization_context["organization"]
    owner = organization_context["owner"]
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Retention policy",
        document_type="Policy",
        description="Retention policy.",
    )
    db_session.add(document)
    db_session.flush()
    create_version(db_session, document, 1, "org/retention/v1.pdf")
    db_session.commit()

    files = FakeFileStorage()
    service = DocumentDeletionService(
        chunk_store=FakeChunkStore(RuntimeError("Qdrant unavailable")),
        summary_store=FakeSummaryStore(),
        file_storage=files,
    )

    with pytest.raises(DocumentDeletionError, match="Qdrant chunk/BM25"):
        service.delete_document(
            db_session,
            document_id=document.id,
            organization_id=organization.id,
        )

    assert db_session.get(Document, document.id) is not None
    assert db_session.query(DocumentVersion).filter_by(document_id=document.id).count() == 1
    assert files.deleted_keys == []
