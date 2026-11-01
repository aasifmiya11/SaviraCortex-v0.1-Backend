from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from app.agents.Document_summarizer.agent import DocumentSummarizerOutput
from app.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
)


class FakeValidator:
    def __init__(self, *, is_valid=True, page_count=2, errors=None, warnings=None):
        self.result = SimpleNamespace(
            is_valid=is_valid,
            page_count=page_count,
            errors=errors or [],
            warnings=warnings or [],
        )

    def validate(self, _path):
        return self.result


class FakeHashService:
    def calculate_file_hash(self, _path):
        return "file-sha256"

    def calculate_content_hash(self, text):
        assert text
        return "content-sha256"


class FakeLoader:
    def __init__(self, pages=None):
        self.pages = pages or [
            Document(
                page_content="First page content.",
                metadata={"page": 1, "ocr_used": False},
            ),
            Document(
                page_content="Second page content.",
                metadata={"page": 2, "ocr_used": True},
            ),
        ]

    def load_pdf(self, _path):
        return self.pages


class FakeSampler:
    def sample(self, pages):
        return pages[:1]


class FakeSummarizer:
    def summarize(self, _pages):
        return DocumentSummarizerOutput(
            title="Employee Leave Policy",
            document_type="Policy",
            department="Human Resources",
            department_confidence="high",
            description="Policy describing employee leave.",
            summary="This policy explains employee leave entitlements.",
        )


class FakeStorage:
    def __init__(self):
        self.upload_file = MagicMock()
        self.exists = MagicMock(return_value=True)
        self.delete_file = MagicMock()
        self.build_document_version_key = MagicMock(
            return_value="voice-ai/documents/doc-id/versions/version-id.pdf"
        )


def make_service(
    tmp_path,
    *,
    classification="no_match",
    registration_error=None,
    upload_error=None,
    validation=None,
    loader=None,
):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 test fixture")

    db = MagicMock()

    @contextmanager
    def session_factory():
        yield db

    matching = MagicMock()
    matching.match.return_value = SimpleNamespace(
        classification=classification
    )

    registration = MagicMock()
    if registration_error is not None:
        registration.register_new_document.side_effect = registration_error
    else:
        registration.register_new_document.return_value = SimpleNamespace(
            document_id="document-id",
            document_version_id="version-id",
            version_number=1,
            status="pending",
            archived=False,
        )

    storage = FakeStorage()
    if upload_error is not None:
        storage.upload_file.side_effect = upload_error

    service = DocumentIngestionService(
        validator=validation or FakeValidator(),
        loader=loader or FakeLoader(),
        hash_service=FakeHashService(),
        sampler=FakeSampler(),
        summarizer=FakeSummarizer(),
        file_storage=storage,
        session_factory=session_factory,
        matching_orchestrator_factory=lambda _db: matching,
        registration_service_factory=lambda _db: registration,
    )

    return service, pdf_path, db, matching, registration, storage


def test_no_match_uploads_original_and_registers_pending_version(tmp_path):
    service, pdf_path, db, matching, registration, storage = make_service(tmp_path)

    result = service.ingest_pdf(pdf_path)

    assert result.status == "registered_pending"
    assert result.original_filename == "sample.pdf"
    assert result.file_hash == "file-sha256"
    assert result.content_hash == "content-sha256"
    assert result.page_count == 2
    assert result.storage_key.endswith(".pdf")
    assert result.registration_result is not None

    storage.upload_file.assert_called_once()
    upload_kwargs = storage.upload_file.call_args.kwargs
    assert upload_kwargs["local_path"] == pdf_path.resolve()
    assert upload_kwargs["content_type"] == "application/pdf"
    assert upload_kwargs["metadata"] == {"file-hash": "file-sha256"}

    registration.register_new_document.assert_called_once()
    registration_kwargs = registration.register_new_document.call_args.kwargs
    assert registration_kwargs["version_data"].storage_key == result.storage_key
    assert registration_kwargs["version_data"].file_hash == "file-sha256"
    assert registration_kwargs["version_data"].content_hash == "content-sha256"
    assert registration_kwargs["version_data"].page_count == 2

    db.commit.assert_called_once()
    db.rollback.assert_not_called()
    storage.delete_file.assert_not_called()


@pytest.mark.parametrize("classification", ["exact_file_match", "exact_content_match"])
def test_exact_duplicate_does_not_upload_or_register(tmp_path, classification):
    service, pdf_path, db, matching, registration, storage = make_service(
        tmp_path, classification=classification
    )

    result = service.ingest_pdf(pdf_path)

    assert result.status == "duplicate"
    assert result.registration_result is None
    assert result.storage_key is None
    storage.upload_file.assert_not_called()
    registration.register_new_document.assert_not_called()
    db.commit.assert_not_called()


def test_potential_match_requires_review_without_upload(tmp_path):
    service, pdf_path, db, matching, registration, storage = make_service(
        tmp_path, classification="potential_match"
    )

    result = service.ingest_pdf(pdf_path)

    assert result.status == "review_required"
    assert result.registration_result is None
    assert result.storage_key is None
    storage.upload_file.assert_not_called()
    registration.register_new_document.assert_not_called()
    db.commit.assert_not_called()


def test_invalid_pdf_stops_before_extraction(tmp_path):
    invalid_validator = FakeValidator(
        is_valid=False,
        errors=["Invalid PDF signature"],
    )
    service, pdf_path, db, matching, registration, storage = make_service(
        tmp_path, validation=invalid_validator
    )

    with pytest.raises(DocumentIngestionError, match="PDF validation failed"):
        service.ingest_pdf(pdf_path)

    storage.upload_file.assert_not_called()
    matching.match.assert_not_called()
    db.commit.assert_not_called()


def test_page_count_mismatch_stops_before_matching(tmp_path):
    loader = FakeLoader(pages=[
        Document(page_content="Only one page", metadata={"page": 1})
    ])
    service, pdf_path, db, matching, registration, storage = make_service(
        tmp_path, loader=loader
    )

    with pytest.raises(DocumentIngestionError, match="page count does not match"):
        service.ingest_pdf(pdf_path)

    matching.match.assert_not_called()
    storage.upload_file.assert_not_called()


def test_upload_failure_rolls_back_and_attempts_cleanup(tmp_path):
    service, pdf_path, db, matching, registration, storage = make_service(
        tmp_path, upload_error=RuntimeError("B2 unavailable")
    )

    with pytest.raises(DocumentIngestionError, match="failed during upload"):
        service.ingest_pdf(pdf_path)

    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    storage.exists.assert_called_once()
    storage.delete_file.assert_called_once()
    registration.register_new_document.assert_not_called()


def test_registration_failure_rolls_back_and_deletes_uploaded_original(tmp_path):
    service, pdf_path, db, matching, registration, storage = make_service(
        tmp_path, registration_error=RuntimeError("Database insert failed")
    )

    with pytest.raises(DocumentIngestionError, match="failed during upload"):
        service.ingest_pdf(pdf_path)

    storage.upload_file.assert_called_once()
    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    storage.exists.assert_called_once()
    storage.delete_file.assert_called_once()


def test_cleanup_failure_is_preserved_on_ingestion_error(tmp_path):
    service, pdf_path, db, matching, registration, storage = make_service(
        tmp_path, registration_error=RuntimeError("Database insert failed")
    )
    storage.exists.side_effect = RuntimeError("B2 cleanup check failed")

    with pytest.raises(DocumentIngestionError) as exc_info:
        service.ingest_pdf(pdf_path)

    assert isinstance(exc_info.value.cleanup_error, RuntimeError)
    assert str(exc_info.value.cleanup_error) == "B2 cleanup check failed"
    db.rollback.assert_called_once()
    storage.delete_file.assert_not_called()
