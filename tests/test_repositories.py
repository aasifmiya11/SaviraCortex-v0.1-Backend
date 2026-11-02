import pytest

from app.core.database import get_db_session
from app.models.organizations import Organization
from app.repositories import DocumentRepository, DocumentVersionRepository


def test_repositories():
    with get_db_session() as db:
        document_repo = DocumentRepository(db)
        version_repo = DocumentVersionRepository(db)
        organization = Organization(name="Repository Test Organization")
        db.add(organization)
        db.flush()

        document = document_repo.create(
            title="Employee Leave Policy",
            document_type="Policy",
            organization_id=organization.id,
            department="Human Resources",
            description="Company employee leave policy.",
        )
        version = version_repo.create(
            document_id=document.id,
            version_number=1,
            version_label="2026",
            original_filename="leave_policy_2026.pdf",
            storage_key=(
                f"documents/{document.id}/versions/leave_policy_2026.pdf"
            ),
            summary="Employee annual and sick leave rules.",
            status="active",
            page_count=32,
            organization_id=organization.id,
        )
        db.commit()

        retrieved = document_repo.get_by_id(
            document.id,
            organization_id=organization.id,
        )
        versions = version_repo.get_by_document(
            document.id,
            organization_id=organization.id,
        )

        assert retrieved is not None
        assert retrieved.id == document.id
        assert version.id == versions[0].id
        assert versions[0].version_number == 1


def test_document_repository_rejects_cross_organization_access():
    with get_db_session() as db:
        try:
            organization_a = Organization(name="Document Isolation A")
            organization_b = Organization(name="Document Isolation B")
            db.add_all([organization_a, organization_b])
            db.flush()

            repository = DocumentRepository(db)
            document = repository.create(
                title="Confidential Policy",
                document_type="Policy",
                organization_id=organization_a.id,
            )

            assert repository.get_by_id(
                document.id,
                organization_id=organization_b.id,
            ) is None
            assert repository.get_by_title(
                "Confidential Policy",
                organization_id=organization_b.id,
            ) == []
            assert repository.get_all(
                organization_id=organization_b.id,
            ) == []

            assert repository.update(
                document.id,
                organization_id=organization_b.id,
                title="Modified by another organization",
            ) is None
            db.refresh(document)
            assert document.title == "Confidential Policy"

            assert repository.delete(
                document.id,
                organization_id=organization_b.id,
            ) is False
            assert repository.get_by_id(
                document.id,
                organization_id=organization_a.id,
            ) is not None
        finally:
            db.rollback()
