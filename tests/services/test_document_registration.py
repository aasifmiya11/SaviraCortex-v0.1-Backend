from uuid import uuid4

import pytest

from app.core.database import get_db_session
from app.models.documents import Document
from app.models.document_versions import DocumentVersion
from app.models.organizations import Organization
from app.services.document_registration import (
    DocumentRegistrationData,
    VersionRegistrationData,
    DocumentRegistrationService,
)


def create_organization(db, name="Test Organization"):
    organization = Organization(name=f"{name} {uuid4()}")
    db.add(organization)
    db.flush()
    return organization


def make_version_data(filename="policy.pdf", version=1):
    return VersionRegistrationData(
        original_filename=filename,
        storage_key=f"voice-ai/test/{uuid4()}/v{version}.pdf",
        file_hash=f"file-{uuid4().hex}",
        content_hash=f"content-{uuid4().hex}",
        summary="Test document summary.",
        page_count=5,
    )


def test_register_new_document():
    with get_db_session() as db:
        organization = create_organization(db)
        service = DocumentRegistrationService(db)

        result = service.register_new_document(
            DocumentRegistrationData(
                title=f"Test Policy {uuid4()}",
                document_type="Policy",
                department="HR",
                description="Test description",
            ),
            make_version_data(),
            organization_id=organization.id,
        )

        document = db.get(Document, result.document_id)
        version = db.get(DocumentVersion, result.document_version_id)

        assert document is not None
        assert version is not None
        assert document.organization_id == organization.id
        assert document.uploaded_by_user_id is None
        assert version.document_id == document.id
        assert version.version_number == 1
        assert version.status == "pending"
        assert document.archived is False

        db.rollback()


def test_register_new_version():
    with get_db_session() as db:
        organization = create_organization(db)
        service = DocumentRegistrationService(db)

        first = service.register_new_document(
            DocumentRegistrationData(
                title=f"Version Test {uuid4()}",
                document_type="Policy",
            ),
            make_version_data("policy_v1.pdf", 1),
            organization_id=organization.id,
        )


        first_version = db.get(
            DocumentVersion,
            first.document_version_id,
        )
        first_version.status = "active"
        db.commit()

        second = service.register_new_version(
            document_id=first.document_id,
            version_data=make_version_data("policy_v2.pdf", 2),
            organization_id=organization.id,
        )

        second_version = db.get(
            DocumentVersion,
            second.document_version_id,
        )

        assert second.version_number == 2
        assert second_version is not None
        assert second_version.status == "pending"
        assert db.get(Document, first.document_id).archived is False
        assert (
            second_version.supersedes_version_id
            == first.document_version_id
        )

        # Registration must not supersede the existing active version.
        assert first_version.status == "active"

        db.rollback()


def test_register_version_for_nonexistent_document():
    with get_db_session() as db:
        organization = create_organization(db)
        service = DocumentRegistrationService(db)

        with pytest.raises(ValueError, match="Document not found"):
            service.register_new_version(
                document_id=uuid4(),
                version_data=make_version_data(),
                organization_id=organization.id,
            )

        db.rollback()


def test_cannot_register_version_for_another_organization():
    with get_db_session() as db:
        organization_a = create_organization(db, "Organization A")
        organization_b = create_organization(db, "Organization B")

        service = DocumentRegistrationService(db)

        result = service.register_new_document(
            DocumentRegistrationData(
                title="Organization A Policy",
                document_type="Policy",
            ),
            make_version_data(),
            organization_id=organization_a.id,
        )

        with pytest.raises(ValueError, match="Document not found"):
            service.register_new_version(
                document_id=result.document_id,
                version_data=make_version_data("policy_v2.pdf", 2),
                organization_id=organization_b.id,
            )

        db.rollback()


def test_cannot_register_version_for_archived_document():
    with get_db_session() as db:
        organization = create_organization(db)
        service = DocumentRegistrationService(db)

        first = service.register_new_document(
            DocumentRegistrationData(
                title=f"Archived Policy {uuid4()}",
                document_type="Policy",
            ),
            make_version_data(),
            organization_id=organization.id,
        )
        service.document_repository.archive(
            first.document_id,
            organization_id=organization.id,
        )

        with pytest.raises(
            ValueError,
            match="Cannot register a new version for an archived document",
        ):
            service.register_new_version(
                document_id=first.document_id,
                version_data=make_version_data("policy_v2.pdf", 2),
                organization_id=organization.id,
            )

        db.rollback()


def test_reject_invalid_page_count():
    with get_db_session() as db:
        organization = create_organization(db)
        service = DocumentRegistrationService(db)

        with pytest.raises(ValueError, match="Page count"):
            service.register_new_document(
                DocumentRegistrationData(
                    title="Invalid Page Count Test",
                    document_type="Policy",
                ),
                VersionRegistrationData(
                    original_filename="invalid.pdf",
                    storage_key="voice-ai/test/invalid.pdf",
                    page_count=0,
                ),
                organization_id=organization.id,
            )

        db.rollback()


def test_reject_empty_document_title():
    with get_db_session() as db:
        organization = create_organization(db)
        service = DocumentRegistrationService(db)

        with pytest.raises(ValueError, match="title"):
            service.register_new_document(
                DocumentRegistrationData(
                    title="   ",
                    document_type="Policy",
                ),
                make_version_data(),
                organization_id=organization.id,
            )

        db.rollback()


def test_register_new_document_with_preassigned_ids():
    organization_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()

    with get_db_session() as db:
        organization = Organization(
            id=organization_id,
            name=f"Preassigned ID Organization {uuid4()}",
        )
        db.add(organization)
        db.flush()

        service = DocumentRegistrationService(db)

        result = service.register_new_document(
            DocumentRegistrationData(
                title=f"Preassigned ID Test {uuid4()}",
                document_type="Policy",
            ),
            make_version_data(),
            organization_id=organization.id,
            document_id=document_id,
            version_id=version_id,
        )

        assert result.document_id == document_id
        assert result.document_version_id == version_id

        document = db.get(Document, document_id)
        version = db.get(DocumentVersion, version_id)

        assert document is not None
        assert version is not None
        assert document.organization_id == organization.id

        db.rollback()