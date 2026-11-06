from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.agents.Document_summarizer.agent import DocumentSummarizerAgent
from app.models.document_ingestion_sessions import DocumentIngestionSession
from app.models.documents import Document
from app.models.document_versions import DocumentVersion
from app.models.organization_departments import OrganizationDepartment
from app.services.document_registration.registration_service import (
    DocumentRegistrationData,
    DocumentRegistrationService,
    VersionRegistrationData,
)
from app.rag.pdf_reader.validator import PDFValidator
from app.rag.pdf_reader.loader import pdf_loader
from app.rag.ingestion.hash_service import PDFHashService
from app.rag.ingestion.text_normalizer import TextNormalizer
from app.rag.ingestion.pdf_sampler import PDFSampler
from app.storage.file_storage import FileStorage


class DocumentIngestionWorkflowError(RuntimeError):
    pass


class DocumentIngestionWorkflowService:
    """Two-phase PDF ingestion: analyze/stage, then persist after user review."""

    SESSION_TTL_HOURS = 24

    def __init__(
        self,
        *,
        validator=None,
        loader=None,
        hash_service=None,
        normalizer=None,
        sampler=None,
        summarizer=None,
        file_storage=None,
        matching_factory=None,
    ) -> None:
        self.validator = validator or PDFValidator(max_file_size_mb=25)
        self.loader = loader or pdf_loader
        self.hash_service = hash_service or PDFHashService()
        self.normalizer = normalizer or TextNormalizer()
        self.sampler = sampler or PDFSampler(max_pages=5)
        # Build the LLM client only when an upload reaches summarization;
        # finalization-only calls and tests do not need an API key.
        self.summarizer = summarizer
        self.file_storage = file_storage or FileStorage()
        self.matching_factory = matching_factory or self._matching_factory

    @staticmethod
    def _matching_factory(db: Session):
        # Import the vector-store adapter lazily so importing the FastAPI router
        # does not initialize Qdrant or embedding clients during application startup.
        from app.repositories.document_version_repositories import DocumentVersionRepository
        from app.services.document_matching.hash_matcher import DocumentHashMatcher
        from app.services.document_matching.summary_matcher import DocumentSummaryMatcher
        from app.services.document_matching.matching_orchestrator import DocumentMatchingOrchestrator
        from app.rag.vector_stores.qdrant_summary import summary_store

        repository = DocumentVersionRepository(db)
        return DocumentMatchingOrchestrator(
            hash_matcher=DocumentHashMatcher(repository),
            summary_matcher=DocumentSummaryMatcher(
                summary_store=summary_store,
                threshold=0.80,
                candidate_limit=20,
            ),
        )

    @staticmethod
    def _acquire_duplicate_locks(
        db: Session,
        organization_id: UUID,
        file_hash: str,
        content_hash: str,
    ) -> None:
        if db.get_bind().dialect.name != "postgresql":
            return
        lock_keys = set()
        for hash_type, hash_value in (("file", file_hash), ("content", content_hash)):
            material = f"voice-ai:duplicate:{organization_id}:{hash_type}:{hash_value}".encode("utf-8")
            digest = hashlib.sha256(material).digest()
            lock_keys.add(int.from_bytes(digest[:8], byteorder="big", signed=True))
        for lock_key in sorted(lock_keys):
            db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    @staticmethod
    def _candidate_payload(result, db: Session | None = None) -> list[dict]:
        candidates: list[dict] = []
        for candidate in result.exact_file_matches:
            candidates.append({
                "document_id": str(candidate.document_id),
                "version_id": str(candidate.version_id),
                "version_number": candidate.version_number,
                "title": (db.scalar(select(Document.title).where(Document.id == candidate.document_id)) or "") if db is not None else "",
                "status": candidate.status,
                "similarity_score": None,
                "matched_by": candidate.matched_by,
            })
        for candidate in result.exact_content_matches:
            if not any(item["version_id"] == str(candidate.version_id) for item in candidates):
                candidates.append({
                    "document_id": str(candidate.document_id),
                    "version_id": str(candidate.version_id),
                    "version_number": candidate.version_number,
                    "title": (db.scalar(select(Document.title).where(Document.id == candidate.document_id)) or "") if db is not None else "",
                    "status": candidate.status,
                    "similarity_score": None,
                    "matched_by": candidate.matched_by,
                })
        for candidate in result.semantic_candidates:
            candidates.append({
                "document_id": candidate.document_id,
                "version_id": candidate.version_id,
                "version_number": candidate.version_number,
                "title": candidate.title,
                "status": candidate.status,
                "similarity_score": candidate.similarity_score,
                "matched_by": None,
            })
        return candidates

    def analyze_and_stage(
        self,
        db: Session,
        file_path: str | Path,
        *,
        organization_id: UUID,
        uploaded_by_user_id: UUID,
        original_filename: str,
        file_size: int,
        progress_callback=None,
    ) -> dict:
        def report(stage: str, state: str, message: str | None = None) -> None:
            if progress_callback is not None:
                try:
                    progress_callback({
                        "stage": stage,
                        "state": state,
                        "message": message,
                    })
                except Exception:
                    # A disconnected progress client must not abort ingestion.
                    pass

        # Opportunistically clean a bounded number of expired staging sessions
        # for this organization; a scheduled worker can call the same method.
        self.cleanup_expired_sessions(db, organization_id=organization_id, limit=25)
        path = Path(file_path).expanduser().resolve()
        report("validate_pdf", "started", "Validating PDF structure and size.")
        validation = self.validator.validate(path)
        if not validation.is_valid:
            raise DocumentIngestionWorkflowError(
                "PDF validation failed: " + "; ".join(validation.errors)
            )
        report("validate_pdf", "completed", "PDF validation completed.")

        report("hash_pdf", "started", "Calculating the SHA-256 file fingerprint.")
        file_hash = self.hash_service.calculate_file_hash(path)
        report("hash_pdf", "completed", "SHA-256 fingerprint calculated.")

        report("parse_pdf", "started", "Extracting PDF text and applying configured OCR.")
        extracted_pages = self.loader.load_pdf(path)
        report("parse_pdf", "completed", f"Extracted {len(extracted_pages)} PDF pages.")
        if len(extracted_pages) != validation.page_count:
            raise DocumentIngestionWorkflowError(
                "Extracted page count does not match the validated PDF page count."
            )

        report("sample_content", "started", "Normalizing extracted page content.")
        normalized_texts = self.normalizer.normalize_pages(
            [page.page_content or "" for page in extracted_pages]
        )
        from langchain_core.documents import Document as LangChainDocument
        normalized_pages = [
            LangChainDocument(
                page_content=text,
                metadata=dict(page.metadata or {}),
            )
            for page, text in zip(extracted_pages, normalized_texts)
        ]
        if not any(page.page_content.strip() for page in normalized_pages):
            raise DocumentIngestionWorkflowError(
                "PDF extraction produced no usable text. Check OCR configuration for scanned PDFs."
            )

        normalized_text = self.normalizer.combine_pages(
            [page.page_content for page in normalized_pages]
        )
        content_hash = self.hash_service.calculate_content_hash(normalized_text)
        sampled_pages = self.sampler.sample(normalized_pages)
        if not sampled_pages:
            raise DocumentIngestionWorkflowError("PDF sampling returned no pages.")
        report("sample_content", "completed", f"Selected {len(sampled_pages)} representative pages.")

        report("summarize", "started", "Generating document metadata and summary.")
        summarizer = self.summarizer or DocumentSummarizerAgent()
        summary_output = summarizer.summarize(sampled_pages)
        report("summarize", "completed", "Document metadata and summary generated.")

        report("duplicate_check", "started", "Checking exact hashes and semantic similarity.")
        self._acquire_duplicate_locks(db, organization_id, file_hash, content_hash)
        staged_duplicate = db.scalar(
            select(DocumentIngestionSession.id)
            .where(
                DocumentIngestionSession.organization_id == organization_id,
                DocumentIngestionSession.status == "awaiting_review",
                DocumentIngestionSession.expires_at > datetime.now(timezone.utc),
                or_(
                    DocumentIngestionSession.file_hash == file_hash,
                    DocumentIngestionSession.content_hash == content_hash,
                ),
            )
            .limit(1)
        )
        if staged_duplicate is not None:
            db.commit()
            report("duplicate_check", "completed", "An identical PDF is already awaiting review.")
            return {
                "status": "duplicate",
                "ingestion_session_id": None,
                "original_filename": original_filename,
                "file_size": file_size,
                "file_hash": file_hash,
                "content_hash": content_hash,
                "page_count": len(normalized_pages),
                "title": summary_output.title,
                "document_type": summary_output.document_type,
                "description": summary_output.description,
                "summary": summary_output.summary,
                "matching_classification": "exact_file_match" if db.scalar(select(DocumentIngestionSession.file_hash).where(DocumentIngestionSession.id == staged_duplicate)) == file_hash else "exact_content_match",
                "matching_candidates": [],
                "validation_warnings": validation.warnings,
                "expires_at": None,
            }

        matching = self.matching_factory(db).match(
            file_hash=file_hash,
            content_hash=content_hash,
            summary=summary_output.summary,
            organization_id=organization_id,
        )
        candidates = self._candidate_payload(matching, db)
        report(
            "duplicate_check",
            "completed",
            f"Duplicate check completed: {matching.classification.replace('_', ' ')}.",
        )

        if matching.classification in {"exact_file_match", "exact_content_match"}:
            db.commit()
            return {
                "status": "duplicate",
                "ingestion_session_id": None,
                "original_filename": original_filename,
                "file_size": file_size,
                "file_hash": file_hash,
                "content_hash": content_hash,
                "page_count": len(normalized_pages),
                "title": summary_output.title,
                "document_type": summary_output.document_type,
                "description": summary_output.description,
                "summary": summary_output.summary,
                "matching_classification": matching.classification,
                "matching_candidates": candidates,
                "validation_warnings": validation.warnings,
                "expires_at": None,
            }

        session_id = uuid4()
        staging_key = self.file_storage.build_ingestion_staging_key(
            organization_id, session_id
        )
        uploaded = False
        try:
            report("store_original", "started", "Storing the original PDF in private Backblaze B2 staging.")
            uploaded = True  # Set before upload: a provider error may occur after object creation.
            self.file_storage.upload_file(
                local_path=path,
                storage_key=staging_key,
                content_type="application/pdf",
                metadata={"file-hash": file_hash, "ingestion-session": str(session_id)},
            )
            expires_at = datetime.now(timezone.utc) + timedelta(hours=self.SESSION_TTL_HOURS)
            staged = DocumentIngestionSession(
                id=session_id,
                organization_id=organization_id,
                uploaded_by_user_id=uploaded_by_user_id,
                staging_storage_key=staging_key,
                original_filename=original_filename,
                file_size=file_size,
                file_hash=file_hash,
                content_hash=content_hash,
                page_count=len(normalized_pages),
                title=summary_output.title,
                document_type=summary_output.document_type,
                description=summary_output.description,
                summary=summary_output.summary,
                matching_classification=matching.classification,
                matching_candidates=candidates,
                status="awaiting_review",
                expires_at=expires_at,
            )
            db.add(staged)
            db.commit()
            report("store_original", "completed", "Original PDF stored and verified in Backblaze B2.")
            return {
                "status": "ready_for_review",
                "ingestion_session_id": session_id,
                "original_filename": original_filename,
                "file_size": file_size,
                "file_hash": file_hash,
                "content_hash": content_hash,
                "page_count": len(normalized_pages),
                "title": summary_output.title,
                "document_type": summary_output.document_type,
                "description": summary_output.description,
                "summary": summary_output.summary,
                "matching_classification": matching.classification,
                "matching_candidates": candidates,
                "validation_warnings": validation.warnings,
                "expires_at": expires_at,
            }
        except Exception:
            db.rollback()
            if uploaded:
                try:
                    self.file_storage.delete_file(staging_key)
                except Exception:
                    pass
            raise

    def finalize(
        self,
        db: Session,
        *,
        organization_id: UUID,
        ingestion_session_id: UUID,
        uploaded_by_user_id: UUID,
        action: str,
        title: str,
        document_type: str,
        description: str,
        department_id: UUID | None = None,
        archived: bool = False,
        target_document_id: UUID | None = None,
    ) -> dict:
        staged = db.scalar(
            select(DocumentIngestionSession)
            .where(
                DocumentIngestionSession.id == ingestion_session_id,
                DocumentIngestionSession.organization_id == organization_id,
            )
            .with_for_update()
        )
        if staged is None:
            raise LookupError("Ingestion session not found.")
        if staged.uploaded_by_user_id != uploaded_by_user_id:
            raise PermissionError("Only the user who uploaded this PDF can finalize it.")
        if staged.status != "awaiting_review":
            raise ValueError("This ingestion session has already been completed or rejected.")

        expires_at = staged.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            staged.status = "expired"
            db.commit()
            try:
                self.file_storage.delete_file(staged.staging_storage_key)
            except Exception:
                pass
            raise TimeoutError("This ingestion session expired. Upload the PDF again.")

        if department_id is not None:
            department = db.scalar(
                select(OrganizationDepartment).where(
                    OrganizationDepartment.id == department_id,
                    OrganizationDepartment.organization_id == organization_id,
                )
            )
            if department is None:
                raise ValueError("The selected department does not belong to this organization.")

        if action not in {"new", "supersede", "independent", "reject"}:
            raise ValueError("Unsupported document ingestion decision.")

        classification = staged.matching_classification
        if action == "new" and classification != "no_match":
            raise ValueError("The new-document action is only valid when no match was found.")
        if action in {"supersede", "independent"} and classification != "potential_match":
            raise ValueError("Supersede or independent ingest is only valid for a potential match.")
        if action == "supersede":
            allowed_targets = {
                UUID(item["document_id"])
                for item in staged.matching_candidates
                if item.get("document_id")
            }
            if target_document_id is None or target_document_id not in allowed_targets:
                raise ValueError("Choose one of the suggested matching documents to supersede.")
            if archived:
                raise ValueError("A superseding version cannot be archived during ingestion.")
        elif target_document_id is not None:
            raise ValueError("target_document_id is only valid for superseding a matched document.")

        if action == "reject":
            staged.status = "rejected"
            db.commit()
            try:
                self.file_storage.delete_file(staged.staging_storage_key)
            except Exception:
                pass
            return {"status": "rejected"}

        # Recheck exact hashes under the same advisory locks used by analysis.
        # This closes the race where another staged upload was finalized first.
        self._acquire_duplicate_locks(
            db, organization_id, staged.file_hash, staged.content_hash
        )
        duplicate_version_id = db.scalar(
            select(DocumentVersion.id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                Document.organization_id == organization_id,
                or_(
                    DocumentVersion.file_hash == staged.file_hash,
                    DocumentVersion.content_hash == staged.content_hash,
                ),
            )
            .limit(1)
        )
        if duplicate_version_id is not None:
            staged.status = "rejected"
            db.commit()
            try:
                self.file_storage.delete_file(staged.staging_storage_key)
            except Exception:
                pass
            raise ValueError("This PDF became an exact duplicate while awaiting review and has been rejected.")

        document_id = target_document_id if action == "supersede" else uuid4()
        version_id = uuid4()
        final_key = self.file_storage.build_document_version_key(
            organization_id=organization_id,
            document_id=document_id,
            version_id=version_id,
        )
        copied = False
        try:
            copied = True  # Copy can succeed remotely before a verification error is raised.
            self.file_storage.copy_file(staged.staging_storage_key, final_key)
            registration = DocumentRegistrationService(db)
            version_data = VersionRegistrationData(
                original_filename=staged.original_filename,
                storage_key=final_key,
                uploaded_by_user_id=uploaded_by_user_id,
                file_hash=staged.file_hash,
                content_hash=staged.content_hash,
                summary=staged.summary,
                version_label="revision" if action == "supersede" else "original",
                page_count=staged.page_count,
            )
            if action == "supersede":
                document = db.scalar(
                    select(Document).where(
                        Document.id == document_id,
                        Document.organization_id == organization_id,
                    ).with_for_update()
                )
                if document is None:
                    raise LookupError("The selected matching document no longer exists.")
                if document.archived:
                    raise ValueError("An archived document cannot be superseded.")
                result = registration.register_new_version(
                    document_id,
                    version_data,
                    organization_id=organization_id,
                    version_id=version_id,
                )
                document.title = title
                document.document_type = document_type
                document.description = description
                document.department_id = department_id
            else:
                result = registration.register_new_document(
                    document_data=DocumentRegistrationData(
                        title=title,
                        document_type=document_type,
                        description=description,
                        department_id=department_id,
                        archived=archived,
                    ),
                    version_data=version_data,
                    organization_id=organization_id,
                    uploaded_by_user_id=uploaded_by_user_id,
                    document_id=document_id,
                    version_id=version_id,
                )
            staged.status = "completed"
            db.commit()
            try:
                self.file_storage.delete_file(staged.staging_storage_key)
            except Exception:
                # The permanent object and database record are committed.
                # An expiry cleanup can remove this orphaned staging copy.
                pass
            return {
                "status": "registered_pending",
                "document_id": result.document_id,
                "document_version_id": result.document_version_id,
                "version_number": result.version_number,
                "version_status": result.status,
                "archived": result.archived,
            }
        except Exception:
            db.rollback()
            if copied:
                try:
                    self.file_storage.delete_file(final_key)
                except Exception:
                    pass
            raise

    def cleanup_expired_sessions(
        self,
        db: Session,
        *,
        organization_id: UUID | None = None,
        limit: int = 100,
    ) -> int:
        """Delete expired staging objects and their session rows.

        Safe to invoke from a scheduled worker. Failed object deletions are
        retained in PostgreSQL so a later cleanup run can retry them.
        """
        if limit < 1:
            raise ValueError("limit must be positive.")
        now = datetime.now(timezone.utc)
        statement = (
            select(DocumentIngestionSession)
            .where(
                DocumentIngestionSession.status.in_(("awaiting_review", "completed", "rejected", "expired")),
                DocumentIngestionSession.expires_at <= now,
            )
            .order_by(DocumentIngestionSession.expires_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if organization_id is not None:
            statement = statement.where(
                DocumentIngestionSession.organization_id == organization_id
            )
        expired = list(db.scalars(statement).all())
        removed = 0
        for item in expired:
            try:
                self.file_storage.delete_file(item.staging_storage_key)
            except Exception:
                continue
            db.delete(item)
            removed += 1
        db.commit()
        return removed
