from datetime import datetime, timedelta, timezone
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

from app.api.v1.endpoints.document_ingestion import get_ingestion_workflow
from app.models import Document, DocumentVersion, Organization, OrganizationMembership, User


class FakeIngestionWorkflow:
    def analyze_and_stage(self, _db, file_path, **kwargs):
        assert file_path
        assert kwargs["original_filename"] == "sample.pdf"
        progress_callback = kwargs.get("progress_callback")
        if progress_callback:
            progress_callback({"stage": "validate_pdf", "state": "started", "message": "Validating."})
            progress_callback({"stage": "validate_pdf", "state": "completed", "message": "Validated."})
        return {
            "status": "ready_for_review",
            "ingestion_session_id": uuid4(),
            "original_filename": "sample.pdf",
            "file_size": kwargs["file_size"],
            "file_hash": "a" * 64,
            "content_hash": "b" * 64,
            "page_count": 2,
            "title": "Suggested title",
            "document_type": "Policy",
            "description": "Suggested description",
            "summary": "Summary",
            "matching_classification": "no_match",
            "matching_candidates": [],
            "validation_warnings": [],
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }

    def finalize(self, _db, **kwargs):
        return {
            "status": "indexed",
            "document_id": uuid4(),
            "document_version_id": uuid4(),
            "version_number": 1,
            "version_status": "active",
            "page_count": 2,
            "chunk_count": 5,
            "archived": False,
        }


def test_authenticated_organization_member_can_analyze_pdf_upload(
    client, organization_context
):
    client.app.dependency_overrides[get_ingestion_workflow] = FakeIngestionWorkflow
    response = client.post(
        f"/api/v1/organizations/{organization_context['organization'].id}/documents/ingestion-sessions",
        files={"file": ("sample.pdf", b"%PDF-1.7 fake", "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready_for_review"
    assert payload["title"] == "Suggested title"
    assert payload["matching_classification"] == "no_match"
    client.app.dependency_overrides.pop(get_ingestion_workflow, None)


def test_document_upload_rejects_non_pdf_filename(client, organization_context):
    client.app.dependency_overrides[get_ingestion_workflow] = FakeIngestionWorkflow
    response = client.post(
        f"/api/v1/organizations/{organization_context['organization'].id}/documents/ingestion-sessions",
        files={"file": ("notes.txt", b"not a pdf", "text/plain")},
    )
    assert response.status_code == 422
    assert "Only PDF" in response.json()["detail"]
    client.app.dependency_overrides.pop(get_ingestion_workflow, None)


def test_document_upload_requires_organization_membership(
    client, db_session, organization_context
):
    user = db_session.query(User).filter_by(firebase_uid="firebase-owner-uid").one()
    other_organization = Organization(name="Other organization")
    db_session.add(other_organization)
    db_session.commit()
    client.app.dependency_overrides[get_ingestion_workflow] = FakeIngestionWorkflow
    response = client.post(
        f"/api/v1/organizations/{other_organization.id}/documents/ingestion-sessions",
        files={"file": ("sample.pdf", b"%PDF-1.7 fake", "application/pdf")},
    )
    assert response.status_code == 404
    client.app.dependency_overrides.pop(get_ingestion_workflow, None)


def test_finalize_endpoint_passes_user_reviewed_metadata_to_workflow(
    client, organization_context
):
    client.app.dependency_overrides[get_ingestion_workflow] = FakeIngestionWorkflow
    session_id = uuid4()
    response = client.post(
        f"/api/v1/organizations/{organization_context['organization'].id}/documents/ingestion-sessions/{session_id}/complete",
        json={
            "action": "new",
            "title": "Reviewed title",
            "document_type": "Policy",
            "description": "Reviewed description",
            "department_id": None,
            "archived": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "indexed"
    client.app.dependency_overrides.pop(get_ingestion_workflow, None)



def test_streaming_upload_emits_real_backend_progress_and_analysis(
    client, organization_context
):
    client.app.dependency_overrides[get_ingestion_workflow] = FakeIngestionWorkflow
    response = client.post(
        f"/api/v1/organizations/{organization_context['organization'].id}/documents/ingestion-sessions/stream",
        files={"file": ("sample.pdf", b"%PDF-1.7 fake", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"stage": "receive_pdf"' in response.text
    assert '"stage": "validate_pdf"' in response.text
    assert '"type": "result"' in response.text
    assert '"matching_classification": "no_match"' in response.text
    client.app.dependency_overrides.pop(get_ingestion_workflow, None)


def test_pending_document_version_can_be_retried_by_its_uploader(
    client, db_session, organization_context, monkeypatch
):
    owner = organization_context["owner"]
    organization = organization_context["organization"]
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Retry policy",
        document_type="Policy",
        description="A policy awaiting indexing.",
    )
    db_session.add(document)
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        version_label="original",
        original_filename="retry-policy.pdf",
        storage_key="documents/retry-policy.pdf",
        file_hash="a" * 64,
        content_hash="b" * 64,
        summary="Policy summary",
        status="pending",
        page_count=2,
        uploaded_by_user_id=owner.id,
    )
    db_session.add(version)
    db_session.commit()

    class FakeIndexer:
        def index_pending_version(self, version_id, *, organization_id):
            assert version_id == version.id
            assert organization_id == organization.id
            version.status = "active"
            db_session.commit()
            return SimpleNamespace(
                document_id=document.id,
                document_version_id=version.id,
                version_number=1,
                status="active",
                page_count=2,
                ocr_page_count=0,
                chunk_count=5,
                summary_sync_pending=False,
                lifecycle_sync_pending=False,
            )

    fake_module = ModuleType("app.services.document_indexing.indexing_orchestrator")
    fake_module.DocumentIndexingOrchestrator = FakeIndexer
    monkeypatch.setitem(
        sys.modules,
        "app.services.document_indexing.indexing_orchestrator",
        fake_module,
    )

    response = client.post(
        f"/api/v1/organizations/{organization.id}/documents/versions/{version.id}/index"
    )

    assert response.status_code == 200
    assert response.json()["version_status"] == "active"
    assert response.json()["chunk_count"] == 5
