from app.core.database import get_db_session
from app.repositories import DocumentRepository, DocumentVersionRepository


def test_repositories():
    with get_db_session() as db:
        document_repo = DocumentRepository(db)
        version_repo = DocumentVersionRepository(db)

        document = document_repo.create(
            title="Employee Leave Policy",
            document_type="Policy",
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
        )
        db.commit()

        retrieved = document_repo.get_by_id(document.id)
        versions = version_repo.get_by_document(document.id)

        assert retrieved is not None
        assert retrieved.id == document.id
        assert version.id == versions[0].id
        assert versions[0].version_number == 1
