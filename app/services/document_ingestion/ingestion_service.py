
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.models.document_versions import DocumentVersion
from app.rag.pdf_reader.validator import PDFValidator
from app.rag.pdf_reader.loader import pdf_loader
from app.rag.ingestion.hash_service import PDFHashService
from app.rag.ingestion.text_normalizer import TextNormalizer
from app.rag.ingestion.pdf_sampler import PDFSampler
from app.agents.Document_summarizer.agent import (
    DocumentSummarizerAgent,
    DocumentSummarizerOutput,
)
from app.repositories import DocumentVersionRepository
from app.services.document_registration.registration_service import (
    DocumentRegistrationData,
    DocumentRegistrationService,
    VersionRegistrationData,
    RegistrationResult,
)
from app.services.document_matching.hash_matcher import (
    DocumentHashMatcher,
)
from app.services.document_matching.summary_matcher import (
    DocumentSummaryMatcher,
)
from app.services.document_matching.matching_orchestrator import (
    DocumentMatchingOrchestrator,
    DocumentMatchingResult,
)
from app.rag.vector_stores.qdrant_summary import summary_store
from app.storage.file_storage import FileStorage


@dataclass(frozen=True, slots=True)
class IngestionResult:
    status: str
    file_path: str
    original_filename: str
    file_hash: str
    content_hash: str
    page_count: int
    summary_output: DocumentSummarizerOutput
    matching_result: DocumentMatchingResult
    registration_result: RegistrationResult | None = None
    storage_key: str | None = None
    validation_warnings: tuple[str, ...] = ()


class DocumentIngestionError(RuntimeError):
    """Raised when ingestion fails."""

    def __init__(
        self,
        message: str,
        cleanup_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.cleanup_error = cleanup_error


class DocumentIngestionService:
    """
    Coordinates PDF validation, extraction, normalization,
    summarization, duplicate detection, B2 upload and registration.

    This initial implementation ends at pending registration.
    It does not index chunks or activate the document version.
    """

    def __init__(
        self,
        *,
        validator: Any | None = None,
        loader: Any | None = None,
        hash_service: Any | None = None,
        normalizer: Any | None = None,
        sampler: Any | None = None,
        summarizer: Any | None = None,
        file_storage: Any | None = None,
        session_factory: Callable | None = None,
        matching_orchestrator_factory: Callable[
            [Session], DocumentMatchingOrchestrator
        ] | None = None,
        registration_service_factory: Callable[
            [Session], DocumentRegistrationService
        ] | None = None,
    ) -> None:

        self.validator = validator or PDFValidator()
        self.loader = loader or pdf_loader
        self.hash_service = hash_service or PDFHashService()
        self.normalizer = normalizer or TextNormalizer()
        self.sampler = sampler or PDFSampler(max_pages=5)
        self.summarizer = summarizer or DocumentSummarizerAgent()
        self.file_storage = file_storage or FileStorage()

        self.session_factory = session_factory or get_db_session

        self.matching_orchestrator_factory = (
            matching_orchestrator_factory
            or self._default_matching_orchestrator
        )

        self.registration_service_factory = (
            registration_service_factory
            or DocumentRegistrationService
        )

    @staticmethod
    def _default_matching_orchestrator(
        db: Session,
    ) -> DocumentMatchingOrchestrator:

        version_repository = DocumentVersionRepository(db)

        hash_matcher = DocumentHashMatcher(
            repository=version_repository
        )

        summary_matcher = DocumentSummaryMatcher(
            summary_store=summary_store,
            threshold=0.80,
            candidate_limit=20,
        )

        return DocumentMatchingOrchestrator(
            hash_matcher=hash_matcher,
            summary_matcher=summary_matcher,
        )

    # @staticmethod
    # def _normalize_pages(
    #     pages: list[Document],
    # ) -> list[Document]:

    #     if not pages:
    #         raise DocumentIngestionError(
    #             "PDF extraction returned no pages."
    #         )

    #     page_texts = [
    #         page.page_content or ""
    #         for page in pages
    #     ]

    #     normalized_texts = TextNormalizer.normalize_pages(
    #         page_texts
    #     )

    #     normalized_documents = []

    #     for page, normalized_text in zip(
    #         pages,
    #         normalized_texts,
    #     ):
    #         normalized_documents.append(
    #             Document(
    #                 page_content=normalized_text,
    #                 metadata=dict(page.metadata or {}),
    #             )
    #         )

    #     return normalized_documents

    def _upload_original(
        self,
        file_path: Path,
        storage_key: str,
        file_hash: str,
    ) -> None:

        self.file_storage.upload_file(
            local_path=file_path,
            storage_key=storage_key,
            content_type="application/pdf",
            metadata={
                "file-hash": file_hash,
            },
        )

    def _cleanup_uploaded_file(
        self,
        storage_key: str,
    ) -> Exception | None:

        try:
            if self.file_storage.exists(storage_key):
                self.file_storage.delete_file(storage_key)

            return None

        except Exception as exc:
            return exc

    def ingest_pdf(
        self,
        file_path: str | Path,
        *,
        organization_id: UUID,
    ) -> IngestionResult:

        if not isinstance(organization_id, UUID):
            raise TypeError("organization_id must be a UUID.")

        path = Path(file_path).expanduser().resolve()

        # --------------------------------------------------
        # 1. Validate PDF
        # --------------------------------------------------

        validation = self.validator.validate(path)

        if not validation.is_valid:
            raise DocumentIngestionError(
                "PDF validation failed: "
                + "; ".join(validation.errors)
            )

        # --------------------------------------------------
        # 2. Hash original PDF bytes
        # --------------------------------------------------

        file_hash = self.hash_service.calculate_file_hash(
            path
        )

        # --------------------------------------------------
        # 3. Extract all pages
        # --------------------------------------------------

        extracted_pages = self.loader.load_pdf(path)

        if len(extracted_pages) != validation.page_count:
            raise DocumentIngestionError(
                "Extracted page count does not match "
                "the validated PDF page count. "
                f"Expected {validation.page_count}, "
                f"received {len(extracted_pages)}."
            )

        # --------------------------------------------------
        # 4. Normalize page content
        # --------------------------------------------------
        
        normalized_texts = self.normalizer.normalize_pages(
            [page.page_content or "" for page in extracted_pages]
        )
        
        normalized_pages = [
            Document(
                page_content=normalized_text,
                metadata=dict(page.metadata or {}),
            )
            for page, normalized_text in zip(extracted_pages, normalized_texts)
        ]

        if not any(
            page.page_content.strip()
            for page in normalized_pages
        ):
            raise DocumentIngestionError(
                "PDF extraction produced no usable text."
            )
        
        normalized_text = self.normalizer.combine_pages(
            [page.page_content for page in normalized_pages]
        )

        content_hash = (
            self.hash_service.calculate_content_hash(
                normalized_text
            )
        )

        # --------------------------------------------------
        # 5. Sample pages for summarization
        # --------------------------------------------------

        sampled_pages = self.sampler.sample(
            normalized_pages
        )

        if not sampled_pages:
            raise DocumentIngestionError(
                "PDF sampling returned no pages."
            )

        # --------------------------------------------------
        # 6. Generate structured metadata and summary
        # --------------------------------------------------

        summary_output = self.summarizer.summarize(
            sampled_pages
        )

        if not isinstance(
            summary_output,
            DocumentSummarizerOutput,
        ):
            raise TypeError(
                "Summarizer must return DocumentSummarizerOutput."
            )

        # --------------------------------------------------
        # 7. Match against existing documents
        # --------------------------------------------------

        with self.session_factory() as db:

            matching_orchestrator = (
                self.matching_orchestrator_factory(db)
            )

            matching_result = matching_orchestrator.match(
                file_hash=file_hash,
                content_hash=content_hash,
                summary=summary_output.summary,
                organization_id=organization_id,
            )

            # Exact duplicate: do not upload or register.
            if matching_result.classification in {
                "exact_file_match",
                "exact_content_match",
            }:
                return IngestionResult(
                    status="duplicate",
                    file_path=str(path),
                    original_filename=path.name,
                    file_hash=file_hash,
                    content_hash=content_hash,
                    page_count=len(normalized_pages),
                    summary_output=summary_output,
                    matching_result=matching_result,
                    validation_warnings=tuple(
                        validation.warnings
                    ),
                )

            # Potential revision: require an explicit decision.
            if matching_result.classification == "potential_match":
                return IngestionResult(
                    status="review_required",
                    file_path=str(path),
                    original_filename=path.name,
                    file_hash=file_hash,
                    content_hash=content_hash,
                    page_count=len(normalized_pages),
                    summary_output=summary_output,
                    matching_result=matching_result,
                    validation_warnings=tuple(
                        validation.warnings
                    ),
                )

            if matching_result.classification != "no_match":
                raise DocumentIngestionError(
                    "Unexpected matching classification: "
                    f"{matching_result.classification}"
                )

            # --------------------------------------------------
            # 8. Allocate IDs and build B2 object key
            # --------------------------------------------------

            document_id = uuid4()
            version_id = uuid4()

            storage_key = (
                self.file_storage.build_document_version_key(
                    organization_id=organization_id,
                    document_id=document_id,
                    version_id=version_id,
                )
            )

            # --------------------------------------------------
            # 9. Upload the original PDF unchanged to B2
            # --------------------------------------------------

            upload_attempted = False

            try:
                upload_attempted = True

                self._upload_original(
                    file_path=path,
                    storage_key=storage_key,
                    file_hash=file_hash,
                )

                # --------------------------------------------------
                # 10. Register a pending document/version
                # --------------------------------------------------

                registration_service = (
                    self.registration_service_factory(db)
                )

                registration_result = (
                    registration_service.register_new_document(
                        document_data=DocumentRegistrationData(
                            title=summary_output.title,
                            document_type=summary_output.document_type,
                            department=summary_output.department,
                            description=summary_output.description,
                        ),
                        version_data=VersionRegistrationData(
                            original_filename=path.name,
                            storage_key=storage_key,
                            file_hash=file_hash,
                            content_hash=content_hash,
                            summary=summary_output.summary,
                            page_count=len(normalized_pages),
                        ),
                        organization_id=organization_id,
                        document_id=document_id,
                        version_id=version_id,
                    )
                )

                # Caller owns the outer transaction.
                db.commit()

            except Exception as exc:

                db.rollback()

                cleanup_error = None

                if upload_attempted:
                    cleanup_error = self._cleanup_uploaded_file(
                        storage_key
                    )

                raise DocumentIngestionError(
                    "Document ingestion failed during upload "
                    "or database registration.",
                    cleanup_error=cleanup_error,
                ) from exc

        return IngestionResult(
            status="registered_pending",
            file_path=str(path),
            original_filename=path.name,
            file_hash=file_hash,
            content_hash=content_hash,
            page_count=len(normalized_pages),
            summary_output=summary_output,
            matching_result=matching_result,
            registration_result=registration_result,
            storage_key=storage_key,
            validation_warnings=tuple(
                validation.warnings
            ),
        )
