
import hashlib
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.database import get_db_session
from app.models.documents import Document
from app.models.document_versions import DocumentVersion
from app.models.organizations import Organization
from app.services.document_ingestion import DocumentIngestionService
from app.storage.file_storage import FileStorage



pytestmark = pytest.mark.integration

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def test_real_pdf_ingestion_persists_original_and_pending_version():
    """
    End-to-end test using the configured LLM, PostgreSQL, Qdrant matching,
    PDF extraction/OCR, and Backblaze B2.

    Uses a locally configured PDF:
        F:\\resume.pdf

    IMPORTANT:
        This test creates a real document/version record in PostgreSQL
        and a persistent object in Backblaze B2.

        Neither is deleted after successful execution.
    """
    configured_path = r"F:\Sajid_Miya_AI_Engineer_resume.pdf"
    organization_id = uuid4()
    pdf_path = Path(configured_path).expanduser().resolve()

    if not pdf_path.exists() or not pdf_path.is_file():
        pytest.fail(
            f"Integration PDF does not exist: {pdf_path}"
        )

    if pdf_path.suffix.lower() != ".pdf":
        pytest.fail(
            "Integration PDF must have a .pdf extension."
        )

    original_hash = _sha256_file(pdf_path)

    with get_db_session() as db:
        db.add(
            Organization(
                id=organization_id,
                name=f"End-to-End Test Organization {organization_id}",
            )
        )
        db.commit()

    service = DocumentIngestionService()

    
    result = service.ingest_pdf(
        pdf_path,
        organization_id=organization_id,
    )

    assert result.status == "registered_pending", (
        "This test requires a PDF that produces a new document. "
        f"Ingestion returned {result.status!r}. If it returned 'duplicate', "
        "choose a PDF that has not already been ingested. If it returned "
        "'review_required', use a document that does not resemble an existing "
        "document closely enough to require manual review."
    )

    assert result.registration_result is not None
    assert result.storage_key
    assert result.file_hash == original_hash
    assert result.registration_result.status == "pending"

    version_id = result.registration_result.document_version_id

    assert isinstance(version_id, UUID)

    # Verify the database record persisted with the expected lifecycle state.
    with get_db_session() as db:
        version = db.get(DocumentVersion, version_id)

        assert version is not None
        assert version.status == "pending"
        document = db.get(Document, version.document_id)
        assert document.archived is False
        assert version.storage_key == result.storage_key
        assert version.file_hash == original_hash
        assert version.original_filename == pdf_path.name
        assert version.page_count == result.page_count

    # Download the original object from B2 and verify byte-for-byte identity.
    storage = FileStorage()

    downloaded = BytesIO()
    storage.download_to_fileobj(
        result.storage_key,
        downloaded,
    )

    stored_bytes = downloaded.getvalue()
    stored_hash = hashlib.sha256(stored_bytes).hexdigest()

    assert stored_hash == original_hash, (
        "The PDF downloaded from B2 does not match the original file."
    )

    assert len(stored_bytes) == pdf_path.stat().st_size

    print("\nReal PDF ingestion succeeded:")
    print(f"  Original file: {pdf_path}")
    print(f"  Document ID: {result.registration_result.document_id}")
    print(f"  Version ID: {version_id}")
    print(
        "  Version number: "
        f"{result.registration_result.version_number}"
    )
    print(f"  Pages: {result.page_count}")
    print(f"  Storage key: {result.storage_key}")
    print(f"  SHA-256: {stored_hash}")
    print("  Database status: pending")
    print("  B2 byte-for-byte verification: passed")
    print("  Original PDF retained in B2: yes")
