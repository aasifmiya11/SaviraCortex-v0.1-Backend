
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event, Lock, current_thread
from uuid import uuid4

import pytest

from app.core.database import SessionLocal, engine
from app.models.organizations import Organization
from app.models.documents import Document
from app.models.document_versions import DocumentVersion
from app.services.document_indexing.indexing_orchestrator import (
    DocumentIndexingOrchestrationError,
    DocumentIndexingOrchestrator,
)



pytestmark = pytest.mark.integration

@contextmanager
def independent_session():
    """Give each worker its own PostgreSQL session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class FakeFileStorage:
    def download_file(self, *, storage_key, destination):
        destination.write_bytes(b"%PDF-1.4 test content")


class FakeLoader:
    def load_pdf(self, path):
        return [object()]


class FakeExternalStore:
    def __init__(self, *, block_cleanup=False):
        self.records = set()
        self.lock = Lock()
        self.cleanup_started = Event()
        self.release_cleanup = Event()
        self.block_cleanup = block_cleanup

    def add(self, value):
        with self.lock:
            self.records.add(value)

    def delete_points(self, point_ids):
        if self.block_cleanup:
            self.cleanup_started.set()
            if not self.release_cleanup.wait(timeout=20):
                raise TimeoutError("Cleanup release timed out.")

        with self.lock:
            self.records.difference_update(point_ids)

    def update_version_status(self, **kwargs):
        pass


class FakeIndexingService:
    def __init__(self, qdrant_store):
        self.qdrant_store = qdrant_store
        self.calls = []
        self.lock = Lock()

    def index_document_version(self, **kwargs):
        worker = current_thread().name

        with self.lock:
            self.calls.append(worker)

        point_id = "shared-test-point"
        self.qdrant_store.add(point_id)

        return type(
            "FakeIndexingResult",
            (),
            {
                "page_count": 1,
                "ocr_page_count": 0,
                "chunk_count": 1,
                "qdrant_point_ids": [point_id],
            },
        )()


class FakeSummaryStorage:
    def __init__(self):
        self.calls = 0
        self.lock = Lock()

    def upsert_summary(self, **kwargs):
        with self.lock:
            self.calls += 1
            call_number = self.calls

        # Worker A fails on its initial pending-summary creation.
        if call_number == 1:
            raise RuntimeError("Simulated summary creation failure.")

        return "test-summary-point"

    def delete_summary(self, version_id):
        pass


def test_cleanup_holds_document_lock_until_external_cleanup_finishes(
    monkeypatch,
):
    if engine.dialect.name != "postgresql":
        pytest.skip("This concurrency test requires PostgreSQL row locks.")

    unique_id = uuid4().hex

    organization = Organization(
        name=f"Concurrency Test Organization {unique_id}"
    )
    document = Document(
        organization=organization,
        title=f"Concurrency Test Document {unique_id}",
        document_type="Policy",
        description="Temporary concurrency regression test.",
    )
    version = DocumentVersion(
        document=document,
        version_number=1,
        original_filename=f"{unique_id}.pdf",
        storage_key=f"test/concurrency/{unique_id}.pdf",
        file_hash=sha256(b"%PDF-1.4 test content").hexdigest(),
        summary="Temporary test summary.",
        status="pending",
        page_count=1,
    )

    # Commit test records so both worker sessions can see them.
    with SessionLocal() as db:
        db.add(organization)
        db.add(document)
        db.add(version)
        db.commit()

        version_id = version.id
        document_id = document.id
        organization_id = organization.id

    qdrant = FakeExternalStore(block_cleanup=True)
    indexing_service = FakeIndexingService(qdrant)
    summary_storage = FakeSummaryStorage()

    orchestrator = DocumentIndexingOrchestrator(
        session_factory=independent_session,
        file_storage=FakeFileStorage(),
        loader=FakeLoader(),
        indexing_service=indexing_service,
        summary_storage=summary_storage,
    )

    worker_b_attempting_load = Event()

    original_load_version = DocumentIndexingOrchestrator._load_version

    def observed_load_version(
        db,
        target_version_id,
        *,
        organization_id,
    ):
        if current_thread().name == "worker-b":
            worker_b_attempting_load.set()

        return original_load_version(
            db,
            target_version_id,
            organization_id=organization_id,
        )

    monkeypatch.setattr(
        DocumentIndexingOrchestrator,
        "_load_version",
        staticmethod(observed_load_version),
    )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Worker A obtains the document lock, indexes, then fails.
            future_a = executor.submit(
                lambda: _run_as_worker(
                    "worker-a",
                    orchestrator,
                    version_id,
                    organization_id,
                )
            )

            # Wait until A enters external cleanup while holding its lock.
            assert qdrant.cleanup_started.wait(timeout=20), (
                "Worker A did not reach external cleanup."
            )

            # Worker B now attempts to load the same version.
            future_b = executor.submit(
                lambda: _run_as_worker(
                    "worker-b",
                    orchestrator,
                    version_id,
                    organization_id,
                )
            )

            assert worker_b_attempting_load.wait(timeout=20), (
                "Worker B did not attempt to load the version."
            )

            # B must remain blocked before its indexing call.
            with indexing_service.lock:
                assert indexing_service.calls == ["worker-a"]

            # Allow A to finish cleanup and release its DB transaction.
            qdrant.release_cleanup.set()

            with pytest.raises(DocumentIndexingOrchestrationError):
                future_a.result(timeout=30)

            result_b = future_b.result(timeout=30)

        assert result_b.status == "active"

        # Both workers indexed, but B did so only after A's cleanup.
        assert indexing_service.calls == ["worker-a", "worker-b"]

        # A's cleanup must not delete B's subsequently indexed records.
        assert "shared-test-point" in qdrant.records

        # PostgreSQL must show the version as active.
        with SessionLocal() as db:
            persisted_version = db.get(
                DocumentVersion,
                version_id,
            )
            assert persisted_version is not None
            assert persisted_version.status == "active"

    finally:
        # Ensure a failed assertion cannot leave worker A blocked.
        qdrant.release_cleanup.set()

        with SessionLocal() as db:
            db.query(DocumentVersion).filter(
                DocumentVersion.id == version_id
            ).delete(synchronize_session=False)

            db.query(Document).filter(
                Document.id == document_id
            ).delete(synchronize_session=False)

            db.query(Organization).filter(
                Organization.id == organization_id
            ).delete(synchronize_session=False)

            db.commit()


def _run_as_worker(name, orchestrator, version_id, organization_id):
    current_thread().name = name
    return orchestrator.index_pending_version(
        version_id,
        organization_id=organization_id,
    )
