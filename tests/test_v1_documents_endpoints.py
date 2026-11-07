from types import SimpleNamespace
from uuid import uuid4

from app.api.v1.endpoints.documents import get_document_deletion_service
from app.core.dependencies import get_verified_firebase_claims
from app.models import Document, DocumentVersion, OrganizationMembership, User


def test_document_library_lists_versions_and_summaries(client, db_session, organization_context):
    organization = organization_context["organization"]
    owner = organization_context["owner"]
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Employee handbook",
        document_type="Policy",
        description="People policies.",
    )
    db_session.add(document)
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        version_label="original",
        original_filename="handbook.pdf",
        storage_key="org/handbook/v1.pdf",
        file_hash="a" * 64,
        content_hash="b" * 64,
        summary="Rules for employees and managers.",
        status="active",
        page_count=12,
    )
    db_session.add(version)
    db_session.commit()

    response = client.get(
        f"/api/v1/organizations/{organization.id}/documents"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(document.id)
    assert payload["items"][0]["versions"][0]["id"] == str(version.id)
    assert payload["items"][0]["versions"][0]["summary"] == "Rules for employees and managers."


def test_document_library_can_update_metadata_and_archive(client, db_session, organization_context):
    organization = organization_context["organization"]
    owner = organization_context["owner"]
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Old title",
        document_type="Policy",
        description="Old description.",
    )
    db_session.add(document)
    db_session.commit()

    response = client.patch(
        f"/api/v1/organizations/{organization.id}/documents/{document.id}",
        json={"title": "Updated title", "description": "Updated description.", "archived": True},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Updated title"
    assert response.json()["description"] == "Updated description."
    assert response.json()["archived"] is True


def test_document_delete_endpoint_requires_owner_or_admin(
    client, db_session, organization_context
):
    organization = organization_context["organization"]
    member = User(
        id=uuid4(),
        firebase_uid="firebase-document-member",
        email="member@example.com",
        display_name="Document Member",
    )
    db_session.add(member)
    db_session.flush()
    db_session.add(
        OrganizationMembership(
            organization_id=organization.id,
            user_id=member.id,
            role="member",
        )
    )
    db_session.commit()
    client.app.dependency_overrides[get_verified_firebase_claims] = lambda: {
        "uid": "firebase-document-member"
    }

    response = client.delete(
        f"/api/v1/organizations/{organization.id}/documents/{uuid4()}"
    )

    assert response.status_code == 403


def test_document_delete_endpoint_calls_document_deletion_service(
    client, db_session, organization_context
):
    organization = organization_context["organization"]
    owner = organization_context["owner"]
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Deletion test document",
        document_type="Policy",
        description="Document used by the deletion endpoint test.",
    )
    db_session.add(document)
    db_session.commit()
    document_id = document.id

    class FakeDeletionService:
        def delete_document(self, _db, *, document_id, organization_id):
            assert organization_id == organization.id
            return SimpleNamespace(
                document_id=document_id,
                deleted_versions=3,
                deleted_files=3,
            )

    client.app.dependency_overrides[get_document_deletion_service] = (
        lambda: FakeDeletionService()
    )
    response = client.delete(
        f"/api/v1/organizations/{organization.id}/documents/{document_id}"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert response.json()["deleted_versions"] == 3
    assert response.json()["deleted_chunk_and_bm25_points"] is True


def test_document_version_summary_edit_persists_and_updates_summary_vector(
    client, db_session, organization_context, monkeypatch
):
    import sys
    from types import ModuleType

    organization = organization_context["organization"]
    owner = organization_context["owner"]
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=owner.id,
        title="Safety handbook",
        document_type="Policy",
        description="Safety policies.",
    )
    db_session.add(document)
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        version_label="original",
        original_filename="safety.pdf",
        storage_key="org/safety/v1.pdf",
        file_hash="c" * 64,
        content_hash="d" * 64,
        summary="Old summary.",
        status="active",
        page_count=8,
    )
    db_session.add(version)
    db_session.commit()

    calls = []
    fake_module = ModuleType("app.rag.vector_stores.qdrant_summary")
    fake_module.summary_store = SimpleNamespace(
        upsert_summary=lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setitem(sys.modules, "app.rag.vector_stores.qdrant_summary", fake_module)

    response = client.patch(
        f"/api/v1/organizations/{organization.id}/documents/{document.id}/versions/{version.id}",
        json={"summary": "Updated summary with revised safety guidance."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"]["summary"] == "Updated summary with revised safety guidance."
    assert payload["summary_index_synced"] is True
    assert db_session.get(DocumentVersion, version.id).summary == payload["version"]["summary"]
    assert len(calls) == 1
    assert calls[0]["document_id"] == document.id
    assert calls[0]["document_version_id"] == version.id
    assert calls[0]["summary"] == payload["version"]["summary"]
