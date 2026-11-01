from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.models.documents import Document
from app.models.document_versions import DocumentVersion
from app.repositories import DocumentVersionRepository
from app.rag.pdf_reader.loader import pdf_loader
from app.rag.vector_stores.qdrant_summary import summary_store
from app.services.document_indexing.indexing_service import (
    DocumentIndexingService,
    IndexingResult,
)
from app.storage.file_storage import FileStorage


@dataclass(frozen=True, slots=True)
class IndexingOrchestrationResult:
    document_id: str
    document_version_id: str
    version_number: int
    page_count: int
    ocr_page_count: int
    chunk_count: int
    qdrant_point_ids: list[str]
    bm25_chunk_ids: list[str]
    summary_point_id: str
    status: str
    summary_sync_pending: bool = False
    lifecycle_sync_pending: bool = False
    sync_errors: list[str] | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_version_id": self.document_version_id,
            "version_number": self.version_number,
            "page_count": self.page_count,
            "ocr_page_count": self.ocr_page_count,
            "chunk_count": self.chunk_count,
            "qdrant_point_ids": self.qdrant_point_ids,
            "bm25_chunk_ids": self.bm25_chunk_ids,
            "summary_point_id": self.summary_point_id,
            "status": self.status,
            "summary_sync_pending": self.summary_sync_pending,
            "lifecycle_sync_pending": self.lifecycle_sync_pending,
            "sync_errors": self.sync_errors or [],
        }


class DocumentIndexingOrchestrationError(RuntimeError):
    """Raised when document indexing orchestration fails."""

    def __init__(
        self,
        message: str,
        cleanup_errors: list[str] | None = None,
    ) -> None:
        self.cleanup_errors = cleanup_errors or []

        if self.cleanup_errors:
            message += (
                "\nCleanup encountered errors:\n- "
                + "\n- ".join(self.cleanup_errors)
            )

        super().__init__(message)


class DocumentIndexingOrchestrator:
    """
    Coordinates indexing and activation of an existing pending version.

    This service does not:
      - Register a document or version.
      - Upload or delete the original PDF.
      - Create FastAPI endpoints.
      - Perform document duplicate detection.

    PostgreSQL is the source of truth for version lifecycle.
    """

    def __init__(
        self,
        *,
        session_factory=None,
        file_storage=None,
        loader=None,
        indexing_service=None,
        summary_storage=None,
    ) -> None:

        self.session_factory = session_factory or get_db_session
        self.file_storage = file_storage or FileStorage()
        self.loader = loader or pdf_loader
        self.indexing_service = (
            indexing_service or DocumentIndexingService()
        )
        self.summary_storage = summary_storage or summary_store

    
    @staticmethod
    def _load_version(
        db: Session,
        version_id: UUID,
    ) -> tuple[DocumentVersion, Document]:

        version = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id
            )
        )

        if version is None:
            raise ValueError(
                f"Document version not found: {version_id}"
            )

        if version.archived:
            raise ValueError(
                "An archived version cannot be indexed."
            )

        if version.status != "pending":
            raise ValueError(
                "Only pending versions can be indexed. "
                f"Current status: {version.status}"
            )

        document = db.get(Document, version.document_id)

        if document is None:
            raise ValueError(
                f"Parent document not found: {version.document_id}"
            )

        if not version.storage_key:
            raise ValueError(
                "Document version has no storage key."
            )

        if not version.summary or not version.summary.strip():
            raise ValueError(
                "Document version has no usable summary."
            )

        if not document.title or not document.title.strip():
            raise ValueError(
                "Parent document has no usable title."
            )

        return version, document

    def _sync_chunk_status(
        self,
        document_version_id: str,
        status: str,
    ) -> list[str]:
        """Synchronize one version's lifecycle status across chunk stores."""

        errors: list[str] = []

        try:
            self.indexing_service.qdrant_store.update_version_status(
                document_version_id=document_version_id,
                status=status,
            )
        except Exception as exc:
            errors.append(
                f"Qdrant status update failed for version "
                f"{document_version_id}: {type(exc).__name__}: {exc}"
            )

        try:
            self.indexing_service.bm25_store.update_version_status(
                document_version_id=document_version_id,
                status=status,
            )
        except Exception as exc:
            errors.append(
                f"BM25 status update failed for version "
                f"{document_version_id}: {type(exc).__name__}: {exc}"
            )

        return errors
    
    def _cleanup(
        self,
        indexing_result: IndexingResult | None,
        version_id: UUID,
        summary_created: bool,
    ) -> list[str]:
        """
        Compensate for indexing operations after a failed activation.

        The original PDF in B2 is intentionally never deleted.
        """

        errors: list[str] = []

        if indexing_result is not None:

            try:
                self.indexing_service.qdrant_store.delete_points(
                    indexing_result.qdrant_point_ids
                )
            except Exception as exc:
                errors.append(
                    f"Qdrant cleanup failed: "
                    f"{type(exc).__name__}: {exc}"
                )

            try:
                self.indexing_service.bm25_store.delete_version(
                    str(version_id)
                )
            except Exception as exc:
                errors.append(
                    f"BM25 cleanup failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        if summary_created:
            try:
                self.summary_storage.delete_summary(version_id)
            except Exception as exc:
                errors.append(
                    f"Summary cleanup failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        return errors

    def index_pending_version(
        self,
        version_id: UUID,
    ) -> IndexingOrchestrationResult:

        indexing_result: IndexingResult | None = None
        summary_created = False
        committed = False

        with self.session_factory() as db:

            try:
                # ------------------------------------------
                # 1. Load and validate the pending version.
                # ------------------------------------------

                version, document = self._load_version(
                    db,
                    version_id,
                )

                document_id = version.document_id
                version_number = version.version_number
                storage_key = version.storage_key
                original_filename = Path(
                    version.original_filename
                ).name

                # ------------------------------------------
                # 2. Download the original PDF from B2.
                # ------------------------------------------

                with tempfile.TemporaryDirectory(
                    prefix="voice_ai_indexing_"
                ) as temporary_directory:

                    local_pdf = (
                        Path(temporary_directory)
                        / original_filename
                    )

                    self.file_storage.download_file(
                        storage_key=storage_key,
                        destination=local_pdf,
                    )

                    if not local_pdf.exists() or local_pdf.stat().st_size == 0:
                        raise IOError(
                            "B2 download produced an empty or missing PDF."
                        )

                    # --------------------------------------
                    # 3. Extract every PDF page.
                    # --------------------------------------

                    page_documents = self.loader.load_pdf(
                        local_pdf
                    )

                    if not page_documents:
                        raise ValueError(
                            "PDF extraction returned no pages."
                        )

                    # --------------------------------------
                    # 4. Index all pages in Qdrant + BM25.
                    # --------------------------------------

                    indexing_result = (
                        self.indexing_service.index_document_version(
                            page_documents=page_documents,
                            document_id=document_id,
                            document_version_id=version_id,
                            version_number=version_number,
                            source_filename=original_filename,
                        )
                    )

                # The temporary PDF is now removed.
                # The original B2 object remains untouched.

                # ------------------------------------------
                # 5. Upsert the summary as pending.
                # ------------------------------------------

                summary_point_id = (
                    self.summary_storage.upsert_summary(
                        document_id=document_id,
                        document_version_id=version_id,
                        version_number=version_number,
                        title=document.title,
                        summary=version.summary,
                        status="pending",
                    )
                )

                summary_created = True

                # ------------------------------------------
                # 6. Update actual extracted page count.
                # ------------------------------------------

                version.page_count = indexing_result.page_count
                db.flush()

                # ------------------------------------------
                # 7. Atomically activate the version.
                # ------------------------------------------

                repository = DocumentVersionRepository(db)

                activation = repository.activate_pending_version(
                    version_id
                )

                if activation is None:
                    raise ValueError(
                        f"Version disappeared during activation: {version_id}"
                    )

                activated_version, previous_version = activation

                previous_version_id = (
                    str(previous_version.id)
                    if previous_version is not None
                    else None
                )

                # Capture values before commit/session close.
                activated_document_id = str(activated_version.document_id)
                activated_version_id = str(activated_version.id)
                activated_version_number = activated_version.version_number
                activated_summary = activated_version.summary
                document_title = document.title

                # ------------------------------------------
                # 8. Commit PostgreSQL lifecycle changes.
                # ------------------------------------------

                db.commit()
                committed = True

            except Exception as exc:

                if not committed:
                    db.rollback()

                    cleanup_errors = self._cleanup(
                        indexing_result=indexing_result,
                        version_id=version_id,
                        summary_created=summary_created,
                    )

                    raise DocumentIndexingOrchestrationError(
                        "Document indexing orchestration failed. "
                        "The PostgreSQL transaction was rolled back.",
                        cleanup_errors=cleanup_errors,
                    ) from exc

                raise

                # ----------------------------------------------
        # 9. Synchronize chunk lifecycle after commit.
        # ----------------------------------------------

        sync_errors: list[str] = []

        # Newly activated version.
        sync_errors.extend(
            self._sync_chunk_status(
                document_version_id=str(version_id),
                status="active",
            )
        )

        # Previously active version, if one existed.
        if previous_version_id is not None:
            sync_errors.extend(
                self._sync_chunk_status(
                    document_version_id=previous_version_id,
                    status="superseded",
                )
            )

        # ----------------------------------------------
        # 10. Synchronize summary lifecycle after commit.
        # ----------------------------------------------

        summary_sync_pending = False

        try:
            self.summary_storage.upsert_summary(
                document_id=activated_document_id,
                document_version_id=activated_version_id,
                version_number=activated_version_number,
                title=document_title,
                summary=activated_summary,
                status="active",
            )

        except Exception as exc:
            summary_sync_pending = True
            sync_errors.append(
                f"Summary status update failed for version "
                f"{version_id}: {type(exc).__name__}: {exc}"
            )

        lifecycle_sync_pending = any(
            error.startswith(("Qdrant status update", "BM25 status update"))
            for error in sync_errors
        )

        return IndexingOrchestrationResult(
            document_id=str(document_id),
            document_version_id=str(version_id),
            version_number=version_number,
            page_count=indexing_result.page_count,
            ocr_page_count=indexing_result.ocr_page_count,
            chunk_count=indexing_result.chunk_count,
            qdrant_point_ids=indexing_result.qdrant_point_ids,
            bm25_chunk_ids=indexing_result.bm25_chunk_ids,
            summary_point_id=str(summary_point_id),
            status="active",
            summary_sync_pending=summary_sync_pending,
            lifecycle_sync_pending=lifecycle_sync_pending,
            sync_errors=sync_errors,
        )