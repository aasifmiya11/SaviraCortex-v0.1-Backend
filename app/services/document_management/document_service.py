from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.document_acl import DocumentACL
from app.models.documents import Document
from app.models.document_versions import DocumentVersion

logger = logging.getLogger(__name__)


class DocumentDeletionError(RuntimeError):
    """Raised when an external document index or object cannot be removed."""


@dataclass(frozen=True, slots=True)
class DocumentDeletionResult:
    document_id: UUID
    deleted_versions: int
    deleted_files: int


class DocumentDeletionService:
    """Delete one logical document and all of its derived/external records.

    Qdrant's chunk collection also hosts native BM25 full-text indexing, so
    deleting its points by metadata.document_id removes both retrieval paths.
    PostgreSQL is changed only after Qdrant and object-storage cleanup succeeds.
    All external deletes are idempotent so a failed operation can be retried.
    """

    def __init__(
        self,
        *,
        chunk_store=None,
        summary_store=None,
        file_storage=None,
    ) -> None:
        self.chunk_store = chunk_store
        self.summary_store = summary_store
        self.file_storage = file_storage

    def _stores(self):
        if self.chunk_store is None:
            from app.rag.vector_stores.qdrant import client as chunk_store
            self.chunk_store = chunk_store
        if self.summary_store is None:
            from app.rag.vector_stores.qdrant_summary import summary_store
            self.summary_store = summary_store
        if self.file_storage is None:
            from app.storage.file_storage import FileStorage
            self.file_storage = FileStorage()
        return self.chunk_store, self.summary_store, self.file_storage

    def delete_document(
        self,
        db: Session,
        *,
        document_id: UUID,
        organization_id: UUID,
    ) -> DocumentDeletionResult:
        document = db.scalar(
            select(Document)
            .where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
            .with_for_update()
        )
        if document is None:
            raise LookupError("Document not found.")

        versions = list(
            db.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
                .order_by(DocumentVersion.version_number)
            ).all()
        )
        storage_keys = [
            version.storage_key
            for version in versions
            if isinstance(version.storage_key, str) and version.storage_key.strip()
        ]

        chunk_store, summary_store, file_storage = self._stores()

        # Keep PostgreSQL intact until every external cleanup has succeeded.
        # Repeating a completed external delete is safe and makes retries useful.
        try:
            chunk_store.delete_document(document_id)
        except Exception as exc:
            logger.exception("Could not delete document chunks (document_id=%s)", document_id)
            raise DocumentDeletionError(
                "The document's Qdrant chunk/BM25 index could not be cleaned. "
                "No database records or source files were deleted."
            ) from exc

        try:
            summary_store.delete_document(document_id)
        except Exception as exc:
            logger.exception("Could not delete document summaries (document_id=%s)", document_id)
            raise DocumentDeletionError(
                "The document's summary vectors could not be cleaned. "
                "The database records and source files were preserved."
            ) from exc

        deleted_files = 0
        for storage_key in storage_keys:
            try:
                delete_permanently = getattr(file_storage, "delete_file_permanently", file_storage.delete_file)
                delete_permanently(storage_key)
                deleted_files += 1
            except Exception as exc:
                logger.exception(
                    "Could not delete document source file (document_id=%s)",
                    document_id,
                )
                raise DocumentDeletionError(
                    "A source PDF could not be removed from object storage. "
                    "The database records were preserved; retry deletion to finish cleanup."
                ) from exc

        # The version-to-version self-FK is RESTRICT, so detach the chain
        # before deleting all versions. ACL rows are removed explicitly.
        db.execute(
            update(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .values(supersedes_version_id=None)
        )
        db.flush()
        db.execute(
            delete(DocumentACL).where(
                DocumentACL.organization_id == organization_id,
                DocumentACL.document_id == document_id,
            )
        )
        db.execute(
            delete(DocumentVersion).where(
                DocumentVersion.document_id == document_id
            )
        )
        db.delete(document)
        db.commit()

        return DocumentDeletionResult(
            document_id=document_id,
            deleted_versions=len(versions),
            deleted_files=deleted_files,
        )
