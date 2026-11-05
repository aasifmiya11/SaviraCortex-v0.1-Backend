"""Ingest evaluation PDFs into an explicitly selected SaviraCortex organization.

This uses the same production ingestion and indexing services as scripts/ingestion.py.
It does not create organizations, users, or memberships.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

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

DEFAULT_ORGANIZATION_ID = UUID("3976ac6b-fd4e-4b44-beda-6c516b45a245")
DEFAULT_SOURCE_DIR = (
    PROJECT_ROOT / "evals" / "dataset_synthesizer" / "corpus" / "source_pdfs"
)


def validate_tenant_access(organization_id: UUID, user_id: UUID) -> None:
    """Require existing organization, user, and membership; never create them."""
    with get_db_session() as db:
        organization = db.scalar(
            select(Organization).where(Organization.id == organization_id)
        )
        if organization is None:
            raise ValueError(f"Organization does not exist: {organization_id}")

        user = db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ValueError(f"User does not exist: {user_id}")

        membership = db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )
        if membership is None:
            raise PermissionError(
                "The supplied user is not a member of this organization. "
                "No membership or permissions were created."
            )


def associate_uploader(
    document_id: UUID,
    organization_id: UUID,
    user_id: UUID,
) -> None:
    """Attach the existing member as uploader of the registered document."""
    with get_db_session() as db:
        document = db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        if document is None:
            raise RuntimeError(f"Registered document was not found: {document_id}")
        document.uploaded_by_user_id = user_id
        db.commit()


def ingest_documents(
    source_dir: Path,
    organization_id: UUID,
    user_id: UUID,
    *,
    skip_index: bool = False,
) -> int:
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source PDF directory does not exist: {source_dir}")

    pdf_paths = sorted(source_dir.glob("*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDF files found in: {source_dir}")

    validate_tenant_access(organization_id, user_id)
    ingestion_service = DocumentIngestionService()
    indexing_service = DocumentIndexingOrchestrator()
    failures = 0

    print(f"Organization ID: {organization_id}")
    print(f"User ID: {user_id}")
    print(f"PDF directory: {source_dir}")
    print(f"PDFs found: {len(pdf_paths)}")
    print("Target Qdrant collections are taken from the application's normal settings.")

    for number, pdf_path in enumerate(pdf_paths, start=1):
        print(f"\n[{number}/{len(pdf_paths)}] Ingesting: {pdf_path.name}")
        try:
            result = ingestion_service.ingest_pdf(
                pdf_path,
                organization_id=organization_id,
            )
            print(f"Ingestion status: {result.status}")

            registration = result.registration_result
            if result.status == "registered_pending" and registration is not None:
                associate_uploader(
                    document_id=registration.document_id,
                    organization_id=organization_id,
                    user_id=user_id,
                )
                print(f"Document ID: {registration.document_id}")
                print(f"Document version ID: {registration.document_version_id}")

                if not skip_index:
                    indexed = indexing_service.index_pending_version(
                        registration.document_version_id,
                        organization_id=organization_id,
                    )
                    print(f"Indexing status: {indexed.status}")
                    print(f"Qdrant chunks indexed: {indexed.chunk_count}")
            elif result.status == "registered_pending":
                raise RuntimeError(
                    "Ingestion returned registered_pending without registration data."
                )

            if result.storage_key:
                print(f"Storage key: {result.storage_key}")
        except Exception as exc:
            failures += 1
            print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\nCompleted with {failures} failure(s) out of {len(pdf_paths)} PDF(s).")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest the evaluation source PDFs into an existing SaviraCortex "
            "organization using the production ingestion/indexing services."
        )
    )
    parser.add_argument(
        "--organization-id",
        type=UUID,
        default=DEFAULT_ORGANIZATION_ID,
        help=f"Existing organization UUID (default: {DEFAULT_ORGANIZATION_ID}).",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        type=UUID,
        help="Existing user UUID who is already a member of the organization.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"Directory containing source PDFs (default: {DEFAULT_SOURCE_DIR}).",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Register/upload PDFs but do not index them into Qdrant.",
    )
    args = parser.parse_args()

    return ingest_documents(
        args.source_dir.expanduser().resolve(),
        args.organization_id,
        args.user_id,
        skip_index=args.skip_index,
    )


if __name__ == "__main__":
    raise SystemExit(main())
