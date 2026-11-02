"""Create a demo tenant and ingest a PDF end to end."""
# .\.venv\Scripts\python.exe scripts\ingestion.py F:\resume.pdf
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import get_db_session
from app.models.documents import Document
from app.models.organization_memberships import OrganizationMembership
from app.models.organizations import Organization
from app.models.users import User
from app.services.document_ingestion import DocumentIngestionService
from app.services.document_indexing.indexing_orchestrator import (
    DocumentIndexingOrchestrator,
)


def create_demo_tenant() -> tuple[Organization, User]:
    """Create a fresh organization and owner user for one ingestion run."""

    run_id = uuid4()

    with get_db_session() as db:
        organization = Organization(
            name=f"Voice AI Demo Organization {run_id}",
        )
        user = User(
            firebase_uid=f"voice-ai-demo-{run_id}",
            email=f"voice-ai-demo-{run_id}@example.invalid",
            display_name="Voice AI Demo User",
        )
        db.add_all([organization, user])
        db.flush()

        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role="owner",
            )
        )
        db.commit()

        return organization, user


def associate_uploader(
    document_id,
    organization_id,
    user_id,
) -> None:
    """Associate the ingested document with its creating user."""

    with get_db_session() as db:
        document = db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        if document is None:
            raise RuntimeError(
                f"Registered document was not found: {document_id}"
            )

        document.uploaded_by_user_id = user_id
        db.commit()


def ingest_pdf(pdf_path: Path, *, skip_index: bool = False) -> None:
    """Create a tenant, ingest the PDF, and optionally index it end to end."""

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF does not exist: {pdf_path}")

    organization, user = create_demo_tenant()
    result = DocumentIngestionService().ingest_pdf(
        pdf_path,
        organization_id=organization.id,
    )

    if result.status == "registered_pending":
        if result.registration_result is None:
            raise RuntimeError(
                "Ingestion returned registered_pending without registration data."
            )
        associate_uploader(
            document_id=result.registration_result.document_id,
            organization_id=organization.id,
            user_id=user.id,
        )

        if not skip_index:
            indexing_result = (
                DocumentIndexingOrchestrator().index_pending_version(
                    result.registration_result.document_version_id,
                    organization_id=organization.id,
                )
            )
        else:
            indexing_result = None
    else:
        indexing_result = None

    print(f"Organization ID: {organization.id}")
    print(f"User ID: {user.id}")
    print(f"Ingestion status: {result.status}")
    print(f"File: {result.file_path}")
    if result.registration_result is not None:
        print(f"Document ID: {result.registration_result.document_id}")
        print(
            "Document version ID: "
            f"{result.registration_result.document_version_id}"
        )
    if result.storage_key:
        print(f"Storage key: {result.storage_key}")
    if indexing_result is not None:
        print(f"Indexing status: {indexing_result.status}")
        print(f"Qdrant chunks: {indexing_result.chunk_count}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a demo tenant and ingest a PDF."
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        type=Path,
        default=Path(r"F:\resume.pdf"),
        help=r"PDF to ingest (default: F:\resume.pdf).",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Stop after pending registration instead of indexing.",
    )
    args = parser.parse_args()
    ingest_pdf(
        args.pdf_path.expanduser().resolve(),
        skip_index=args.skip_index,
    )


if __name__ == "__main__":
    main()
