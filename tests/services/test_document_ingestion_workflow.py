from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document as LangChainDocument

from app.agents.Document_summarizer.agent import DocumentSummarizerOutput
from app.models import Document, DocumentVersion, DocumentIngestionSession
from app.services.document_ingestion.workflow_service import (
    DocumentIngestionWorkflowService,
)


class FakeStorage:
    def __init__(self):
        self.uploads = []
        self.copies = []
        self.deletes = []

    def build_ingestion_staging_key(self, organization_id, session_id):
        return f"staging/{organization_id}/{session_id}.pdf"

    def build_document_version_key(self, organization_id, document_id, version_id):
        return f"documents/{organization_id}/{document_id}/{version_id}.pdf"

    def upload_file(self, **kwargs):
        self.uploads.append(kwargs)

    def copy_file(self, source, destination):
        self.copies.append((source, destination))

    def delete_file(self, key):
        self.deletes.append(key)


class FakeIndexingOrchestrator:
    def __init__(self, db_session, *, fail=False):
        self.db_session = db_session
        self.fail = fail
        self.calls = []

    def index_pending_version(self, version_id, *, organization_id):
        self.calls.append((version_id, organization_id))
        if self.fail:
            raise RuntimeError("simulated Qdrant indexing failure")

        version = self.db_session.get(DocumentVersion, version_id)
        active_versions = (
            self.db_session.query(DocumentVersion)
            .filter(
                DocumentVersion.document_id == version.document_id,
                DocumentVersion.status == "active",
            )
            .all()
        )
        for previous in active_versions:
            previous.status = "superseded"
        self.db_session.flush()
        version.status = "active"
        self.db_session.commit()
        return SimpleNamespace(
            status="active",
            page_count=2,
            ocr_page_count=0,
            chunk_count=4,
            summary_sync_pending=False,
            lifecycle_sync_pending=False,
        )

def staged_session(context, *, classification="no_match", candidates=None):
    return DocumentIngestionSession(
        id=uuid4(),
        organization_id=context["organization"].id,
        uploaded_by_user_id=context["owner"].id,
        staging_storage_key="staging/upload.pdf",
        original_filename="policy.pdf",
        file_size=1024,
        file_hash="a" * 64,
        content_hash="b" * 64,
        page_count=2,
        title="Suggested title",
        document_type="Policy",
        description="Suggested description",
        summary="A summary of the policy.",
        matching_classification=classification,
        matching_candidates=candidates or [],
        status="awaiting_review",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_finalize_new_document_persists_reviewed_metadata_and_indexes_version(
    db_session, organization_context
):
    storage = FakeStorage()
    indexing = FakeIndexingOrchestrator(db_session)
    workflow = DocumentIngestionWorkflowService(file_storage=storage, indexing_orchestrator=indexing)
    staged = staged_session(organization_context)
    db_session.add(staged)
    db_session.commit()

    result = workflow.finalize(
        db_session,
        organization_id=organization_context["organization"].id,
        ingestion_session_id=staged.id,
        uploaded_by_user_id=organization_context["owner"].id,
        action="new",
        title="Reviewed title",
        document_type="Policy",
        description="Reviewed description",
        archived=True,
    )

    document = db_session.get(Document, result["document_id"])
    version = db_session.get(DocumentVersion, result["document_version_id"])
    assert result["status"] == "indexed"
    assert result["version_number"] == 1
    assert document.title == "Reviewed title"
    assert document.archived is True
    assert document.uploaded_by_user_id == organization_context["owner"].id
    assert version.status == "active"
    assert version.uploaded_by_user_id == organization_context["owner"].id
    assert version.version_label == "original"
    assert version.storage_key == storage.copies[0][1]
    assert staged.status == "completed"
    assert indexing.calls == [(version.id, organization_context["organization"].id)]
    assert storage.deletes == ["staging/upload.pdf"]



def test_finalize_keeps_permanent_pdf_and_pending_version_when_indexing_fails(
    db_session, organization_context
):
    storage = FakeStorage()
    indexing = FakeIndexingOrchestrator(db_session, fail=True)
    workflow = DocumentIngestionWorkflowService(
        file_storage=storage,
        indexing_orchestrator=indexing,
    )
    staged = staged_session(organization_context)
    db_session.add(staged)
    db_session.commit()

    result = workflow.finalize(
        db_session,
        organization_id=organization_context["organization"].id,
        ingestion_session_id=staged.id,
        uploaded_by_user_id=organization_context["owner"].id,
        action="new",
        title="Reviewed title",
        document_type="Policy",
        description="Reviewed description",
    )

    version = db_session.get(DocumentVersion, result["document_version_id"])
    assert result["status"] == "indexing_failed"
    assert result["version_status"] == "pending"
    assert version.status == "pending"
    assert version.storage_key == storage.copies[0][1]
    assert storage.deletes == ["staging/upload.pdf"]
    assert "Retry indexing" in result["indexing_error"]

def test_finalize_supersede_creates_next_version_under_matched_document(
    db_session, organization_context
):
    storage = FakeStorage()
    indexing = FakeIndexingOrchestrator(db_session)
    workflow = DocumentIngestionWorkflowService(file_storage=storage, indexing_orchestrator=indexing)
    owner = organization_context["owner"]
    organization = organization_context["organization"]
    existing = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Old policy",
        document_type="Policy",
        description="Old description",
    )
    db_session.add(existing)
    db_session.flush()
    previous = DocumentVersion(
        document_id=existing.id,
        version_number=1,
        version_label="original",
        original_filename="old.pdf",
        storage_key="documents/old.pdf",
        file_hash="c" * 64,
        content_hash="d" * 64,
        summary="Old summary",
        status="active",
        page_count=2,
    )
    db_session.add(previous)
    db_session.flush()
    staged = staged_session(
        organization_context,
        classification="exact_file_match",
        candidates=[{
            "document_id": str(existing.id),
            "version_id": str(previous.id),
            "version_number": 1,
            "title": "Old policy",
            "status": "active",
            "similarity_score": 0.91,
            "matched_by": None,
        }],
    )
    db_session.add(staged)
    db_session.commit()

    result = workflow.finalize(
        db_session,
        organization_id=organization.id,
        ingestion_session_id=staged.id,
        uploaded_by_user_id=owner.id,
        action="supersede",
        target_document_id=existing.id,
        title="Updated policy",
        document_type="Policy",
        description="Updated description",
    )

    versions = (
        db_session.query(DocumentVersion)
        .filter(DocumentVersion.document_id == existing.id)
        .order_by(DocumentVersion.version_number)
        .all()
    )
    assert result["status"] == "indexed"
    assert result["document_id"] == existing.id
    assert result["version_number"] == 2
    assert len(versions) == 2
    assert versions[1].status == "active"
    assert versions[1].supersedes_version_id == previous.id
    assert versions[1].version_label == "revision"
    assert versions[1].uploaded_by_user_id == owner.id
    assert versions[0].status == "superseded"
    assert existing.title == "Updated policy"


def test_reject_discards_staged_file_without_creating_document(
    db_session, organization_context
):
    storage = FakeStorage()
    workflow = DocumentIngestionWorkflowService(file_storage=storage)
    staged = staged_session(organization_context, classification="potential_match")
    db_session.add(staged)
    db_session.commit()

    result = workflow.finalize(
        db_session,
        organization_id=organization_context["organization"].id,
        ingestion_session_id=staged.id,
        uploaded_by_user_id=organization_context["owner"].id,
        action="reject",
        title="Title",
        document_type="Policy",
        description="Description",
    )

    assert result == {"status": "rejected"}
    assert staged.status == "rejected"
    assert storage.copies == []
    assert storage.deletes == ["staging/upload.pdf"]
    assert db_session.query(Document).count() == 0


def test_supersede_rejects_document_not_in_match_candidates(
    db_session, organization_context
):
    storage = FakeStorage()
    workflow = DocumentIngestionWorkflowService(file_storage=storage)
    staged = staged_session(organization_context, classification="potential_match")
    db_session.add(staged)
    db_session.commit()

    with pytest.raises(ValueError, match="suggested matching documents"):
        workflow.finalize(
            db_session,
            organization_id=organization_context["organization"].id,
            ingestion_session_id=staged.id,
            uploaded_by_user_id=organization_context["owner"].id,
            action="supersede",
            target_document_id=uuid4(),
            title="Title",
            document_type="Policy",
            description="Description",
        )
    assert storage.copies == []


def test_finalize_rejects_another_users_ingestion_session(
    db_session, organization_context
):
    storage = FakeStorage()
    workflow = DocumentIngestionWorkflowService(file_storage=storage)
    staged = staged_session(organization_context)
    db_session.add(staged)
    db_session.commit()

    with pytest.raises(PermissionError, match="uploaded this PDF"):
        workflow.finalize(
            db_session,
            organization_id=organization_context["organization"].id,
            ingestion_session_id=staged.id,
            uploaded_by_user_id=uuid4(),
            action="new",
            title="Title",
            document_type="Policy",
            description="Description",
        )
    assert storage.copies == []


def test_finalize_rejects_expired_ingestion_session(
    db_session, organization_context
):
    storage = FakeStorage()
    workflow = DocumentIngestionWorkflowService(file_storage=storage)
    staged = staged_session(organization_context)
    staged.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.add(staged)
    db_session.commit()

    with pytest.raises(TimeoutError, match="expired"):
        workflow.finalize(
            db_session,
            organization_id=organization_context["organization"].id,
            ingestion_session_id=staged.id,
            uploaded_by_user_id=organization_context["owner"].id,
            action="new",
            title="Title",
            document_type="Policy",
            description="Description",
        )
    assert staged.status == "expired"
    assert storage.deletes == ["staging/upload.pdf"]


class FakeValidator:
    def validate(self, _path):
        return SimpleNamespace(is_valid=True, page_count=1, warnings=[], errors=[])


class FakeLoader:
    def load_pdf(self, _path):
        return [LangChainDocument(page_content="Policy text.", metadata={"page": 1})]


class FakeHashService:
    def calculate_file_hash(self, _path):
        return "1" * 64

    def calculate_content_hash(self, _text):
        return "2" * 64


class FakeNormalizer:
    def normalize_pages(self, pages):
        return [value.strip() for value in pages]

    def combine_pages(self, pages):
        return "\n".join(pages)


class FakeSampler:
    def sample(self, pages):
        return pages


class FakeSummarizer:
    def summarize(self, _pages):
        return DocumentSummarizerOutput(
            title="AI title",
            document_type="Policy",
            description="AI description",
            summary="AI summary",
        )


def test_analyze_and_stage_runs_pipeline_and_stages_non_duplicate_pdf(
    db_session, organization_context, tmp_path
):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.7 test")
    storage = FakeStorage()
    matching = SimpleNamespace(
        classification="no_match",
        exact_file_matches=(),
        exact_content_matches=(),
        semantic_candidates=(),
    )
    workflow = DocumentIngestionWorkflowService(
        validator=FakeValidator(),
        loader=FakeLoader(),
        hash_service=FakeHashService(),
        normalizer=FakeNormalizer(),
        sampler=FakeSampler(),
        summarizer=FakeSummarizer(),
        file_storage=storage,
        matching_factory=lambda _db: SimpleNamespace(match=lambda **_kwargs: matching),
    )

    progress_events = []
    result = workflow.analyze_and_stage(
        db_session,
        pdf,
        organization_id=organization_context["organization"].id,
        uploaded_by_user_id=organization_context["owner"].id,
        original_filename="sample.pdf",
        file_size=pdf.stat().st_size,
        progress_callback=progress_events.append,
    )

    assert [event["stage"] for event in progress_events if event["state"] == "completed"] == [
        "validate_pdf",
        "hash_pdf",
        "parse_pdf",
        "sample_content",
        "summarize",
        "duplicate_check",
        "store_original",
    ]
    assert result["status"] == "ready_for_review"
    assert result["title"] == "AI title"
    assert result["matching_classification"] == "no_match"
    assert result["ingestion_session_id"] is not None
    assert len(storage.uploads) == 1
    saved = db_session.get(DocumentIngestionSession, result["ingestion_session_id"])
    assert saved.file_hash == "1" * 64
    assert saved.status == "awaiting_review"


def test_analyze_and_stage_exact_duplicate_is_staged_for_user_review(
    db_session, organization_context, tmp_path
):
    pdf = tmp_path / "duplicate.pdf"
    pdf.write_bytes(b"%PDF-1.7 duplicate")
    storage = FakeStorage()
    match_candidate = SimpleNamespace(
        document_id=uuid4(),
        version_id=uuid4(),
        version_number=1,
        status="active",
        matched_by="file_hash",
    )
    matching = SimpleNamespace(
        classification="exact_file_match",
        exact_file_matches=(match_candidate,),
        exact_content_matches=(),
        semantic_candidates=(),
    )
    workflow = DocumentIngestionWorkflowService(
        validator=FakeValidator(),
        loader=FakeLoader(),
        hash_service=FakeHashService(),
        normalizer=FakeNormalizer(),
        sampler=FakeSampler(),
        summarizer=FakeSummarizer(),
        file_storage=storage,
        matching_factory=lambda _db: SimpleNamespace(match=lambda **_kwargs: matching),
    )

    result = workflow.analyze_and_stage(
        db_session,
        pdf,
        organization_id=organization_context["organization"].id,
        uploaded_by_user_id=organization_context["owner"].id,
        original_filename="duplicate.pdf",
        file_size=pdf.stat().st_size,
    )

    assert result["status"] == "ready_for_review"
    assert result["matching_candidates"][0]["matched_by"] == "file_hash"
    assert len(storage.uploads) == 1
    assert db_session.query(DocumentIngestionSession).count() == 1

def test_analyze_rejects_duplicate_that_is_already_awaiting_review(
    db_session, organization_context, tmp_path
):
    pdf = tmp_path / "duplicate-staged.pdf"
    pdf.write_bytes(b"%PDF-1.7 duplicate staged")
    storage = FakeStorage()
    pending = staged_session(organization_context)
    db_session.add(pending)
    db_session.commit()
    workflow = DocumentIngestionWorkflowService(
        validator=FakeValidator(),
        loader=FakeLoader(),
        hash_service=SimpleNamespace(
            calculate_file_hash=lambda _path: "a" * 64,
            calculate_content_hash=lambda _text: "b" * 64,
        ),
        normalizer=FakeNormalizer(),
        sampler=FakeSampler(),
        summarizer=FakeSummarizer(),
        file_storage=storage,
        matching_factory=lambda _db: (_ for _ in ()).throw(AssertionError("matcher should not run")),
    )

    result = workflow.analyze_and_stage(
        db_session,
        pdf,
        organization_id=organization_context["organization"].id,
        uploaded_by_user_id=organization_context["owner"].id,
        original_filename="duplicate-staged.pdf",
        file_size=pdf.stat().st_size,
    )

    assert result["status"] == "duplicate"
    assert result["matching_candidates"] == []
    assert storage.uploads == []


def test_finalize_rechecks_hashes_before_persisting_staged_upload(
    db_session, organization_context
):
    storage = FakeStorage()
    workflow = DocumentIngestionWorkflowService(file_storage=storage)
    owner = organization_context["owner"]
    organization = organization_context["organization"]
    existing = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Existing",
        document_type="Policy",
    )
    db_session.add(existing)
    db_session.flush()
    db_session.add(DocumentVersion(
        document_id=existing.id,
        version_number=1,
        original_filename="existing.pdf",
        storage_key="documents/existing.pdf",
        file_hash="a" * 64,
        content_hash="b" * 64,
        summary="Existing summary",
        status="active",
        page_count=2,
    ))
    staged = staged_session(organization_context)
    db_session.add(staged)
    db_session.commit()

    with pytest.raises(ValueError, match="added while this upload awaited review"):
        workflow.finalize(
            db_session,
            organization_id=organization.id,
            ingestion_session_id=staged.id,
            uploaded_by_user_id=owner.id,
            action="new",
            title="New",
            document_type="Policy",
            description="New description",
        )

    assert staged.status == "awaiting_review"
    assert storage.copies == []
    assert storage.deletes == []
    assert db_session.query(Document).count() == 1
