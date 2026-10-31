import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import get_db_session
from app.repositories import (
    DocumentRepository,
    DocumentVersionRepository,
)


def test_repositories():

    with get_db_session() as db:

        document_repo = DocumentRepository(db)
        version_repo = DocumentVersionRepository(db)

        try:
            # Create a logical document.
            document = document_repo.create(
                title="Employee Leave Policy",
                document_type="Policy",
                department="Human Resources",
                description="Company employee leave policy.",
            )

            # Create its first version.
            version = version_repo.create(
                document_id=document.id,
                version_number=1,
                version_label="2026",
                original_filename="leave_policy_2026.pdf",
                summary="Employee annual and sick leave rules.",
                status="active",
                page_count=32,
            )

            # Commit both operations together.
            db.commit()

            print("Document created:", document.id)
            print("Version created:", version.id)

            # Retrieve document.
            retrieved = document_repo.get_by_id(document.id)
            print("Retrieved:", retrieved)

            # Retrieve version history.
            versions = version_repo.get_by_document(document.id)

            for item in versions:
                print(
                    item.id,
                    item.version_number,
                    item.status,
                )

        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    test_repositories()
