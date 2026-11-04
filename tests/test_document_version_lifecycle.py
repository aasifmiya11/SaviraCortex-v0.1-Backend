
import uuid

import pytest

from app.core.database import get_db_session
from app.models.organizations import Organization
from app.repositories import (
    DocumentRepository,
    DocumentVersionRepository,
)


def create_document_and_version(
    db,
    status="pending",
    file_hash=None,
    content_hash=None,
):
    document_repo = DocumentRepository(db)
    version_repo = DocumentVersionRepository(db)

    unique_id = uuid.uuid4().hex
    organization = Organization(
        name=f"Lifecycle Test Organization {unique_id}"
    )
    db.add(organization)
    db.flush()

    document = document_repo.create(
        title=f"Lifecycle Test Document {unique_id}",
        document_type="Policy",
        organization_id=organization.id,
        description="Document for lifecycle tests.",
    )

    version = version_repo.create(
        document_id=document.id,
        version_number=1,
        original_filename=f"test_{unique_id}.pdf",
        storage_key=f"test/documents/{unique_id}.pdf",
        file_hash=file_hash,
        content_hash=content_hash,
        summary="Test document summary.",
        status=status,
        page_count=5,
        organization_id=organization.id,
    )

    return document, version


def test_new_document_defaults_to_not_archived():
    with get_db_session() as db:
        try:
            document, version = create_document_and_version(db)

            assert document.archived is False
            assert version.status == "pending"

        finally:
            db.rollback()


def test_document_archive_excludes_all_versions_without_changing_status():
    with get_db_session() as db:
        try:
            document, active_version = create_document_and_version(
                db,
                status="active",
            )
            version_repo = DocumentVersionRepository(db)
            historical_version = version_repo.create(
                document_id=document.id,
                version_number=2,
                original_filename="historical.pdf",
                storage_key=f"test/documents/{uuid.uuid4().hex}.pdf",
                summary="Historical version.",
                status="superseded",
                page_count=5,
                organization_id=document.organization_id,
            )

            document_repo = DocumentRepository(db)
            archived = document_repo.archive(
                document.id,
                organization_id=document.organization_id,
            )

            assert archived is not None
            assert archived.archived is True
            assert active_version.status == "active"
            assert historical_version.status == "superseded"
            assert version_repo.get_active_version(
                document.id,
                organization_id=document.organization_id,
            ) is None
            assert version_repo.get_retrieval_eligible_versions(
                document.id,
                organization_id=document.organization_id,
            ) == []
        finally:
            db.rollback()


def test_document_unarchive_restores_version_eligibility():
    with get_db_session() as db:
        try:
            document, active_version = create_document_and_version(
                db,
                status="active",
            )
            version_repo = DocumentVersionRepository(db)
            historical_version = version_repo.create(
                document_id=document.id,
                version_number=2,
                original_filename="historical.pdf",
                storage_key=f"test/documents/{uuid.uuid4().hex}.pdf",
                summary="Historical version.",
                status="superseded",
                page_count=5,
                organization_id=document.organization_id,
            )
            document_repo = DocumentRepository(db)

            document_repo.archive(
                document.id,
                organization_id=document.organization_id,
            )
            document_repo.unarchive(
                document.id,
                organization_id=document.organization_id,
            )

            assert document.archived is False
            assert active_version.status == "active"
            assert historical_version.status == "superseded"
            assert version_repo.get_active_version(
                document.id,
                organization_id=document.organization_id,
            ).id == active_version.id
            assert {
                version.id
                for version in version_repo.get_retrieval_eligible_versions(
                    document.id,
                    organization_id=document.organization_id,
                )
            } == {active_version.id, historical_version.id}
        finally:
            db.rollback()


def test_archived_documents_are_included_in_hash_matching():
    with get_db_session() as db:
        try:
            file_hash = uuid.uuid4().hex
            content_hash = uuid.uuid4().hex
            document, version = create_document_and_version(
                db,
                status="active",
                file_hash=file_hash,
                content_hash=content_hash,
            )
            DocumentRepository(db).archive(
                document.id,
                organization_id=document.organization_id,
            )

            matches = DocumentVersionRepository(db).get_by_hash(
                file_hash=file_hash,
                content_hash=content_hash,
                organization_id=document.organization_id,
            )

            assert [match.id for match in matches] == [version.id]
            assert document.archived is True
        finally:
            db.rollback()


def test_hash_lookup_is_scoped_to_organization():
    with get_db_session() as db:
        try:
            shared_file_hash = uuid.uuid4().hex
            shared_content_hash = uuid.uuid4().hex
            organization_a = Organization(name=f"Hash Org A {uuid.uuid4()}")
            organization_b = Organization(name=f"Hash Org B {uuid.uuid4()}")
            db.add_all([organization_a, organization_b])
            db.flush()

            document_a, version_a = create_document_and_version(
                db,
                file_hash=shared_file_hash,
                content_hash=shared_content_hash,
            )
            document_b, version_b = create_document_and_version(
                db,
                file_hash=shared_file_hash,
                content_hash=shared_content_hash,
            )
            document_a.organization_id = organization_a.id
            document_b.organization_id = organization_b.id
            db.flush()

            repository = DocumentVersionRepository(db)

            matches_a = repository.get_by_hash(
                file_hash=shared_file_hash,
                content_hash=shared_content_hash,
                organization_id=organization_a.id,
            )
            matches_b = repository.get_by_hash(
                file_hash=shared_file_hash,
                content_hash=shared_content_hash,
                organization_id=organization_b.id,
            )

            assert [version.id for version in matches_a] == [version_a.id]
            assert [version.id for version in matches_b] == [version_b.id]
        finally:
            db.rollback()


def test_version_repository_rejects_cross_organization_access():
    with get_db_session() as db:
        try:
            document, version = create_document_and_version(
                db,
                status="active",
            )
            another_organization = Organization(
                name=f"Unauthorized Org {uuid.uuid4()}"
            )
            db.add(another_organization)
            db.flush()
            repository = DocumentVersionRepository(db)
            wrong_org_id = another_organization.id

            assert repository.get_by_id(
                version.id,
                organization_id=wrong_org_id,
            ) is None
            assert repository.get_by_document(
                document.id,
                organization_id=wrong_org_id,
            ) == []
            assert repository.get_active_version(
                document.id,
                organization_id=wrong_org_id,
            ) is None
            assert repository.get_retrieval_eligible_versions(
                document.id,
                organization_id=wrong_org_id,
            ) == []

            assert repository.update(
                version.id,
                organization_id=wrong_org_id,
                summary="Unauthorized modification",
            ) is None
            assert repository.change_status(
                version.id,
                "superseded",
                organization_id=wrong_org_id,
            ) is None
            assert repository.activate_pending_version(
                version.id,
                organization_id=wrong_org_id,
            ) is None
            assert repository.delete(
                version.id,
                organization_id=wrong_org_id,
            ) is False

            db.refresh(version)
            assert version.summary == "Test document summary."
            assert version.status == "active"
            assert document.archived is False
        finally:
            db.rollback()


def test_cannot_create_version_for_another_organizations_document():
    with get_db_session() as db:
        try:
            document, _ = create_document_and_version(db)
            another_organization = Organization(
                name=f"Version Creation Org {uuid.uuid4()}"
            )
            db.add(another_organization)
            db.flush()
            repository = DocumentVersionRepository(db)

            with pytest.raises(ValueError, match="Document not found"):
                repository.create(
                    document_id=document.id,
                    version_number=2,
                    original_filename="unauthorized.pdf",
                    storage_key="unauthorized/file.pdf",
                    status="pending",
                    organization_id=another_organization.id,
                )
        finally:
            db.rollback()


def test_cannot_archive_another_organizations_document():
    with get_db_session() as db:
        try:
            document, _ = create_document_and_version(db)

            another_organization = Organization(
                name=f"Archive Isolation {uuid.uuid4()}"
            )
            db.add(another_organization)
            db.flush()

            assert DocumentRepository(db).archive(
                document.id,
                organization_id=another_organization.id,
            ) is None

            assert document.archived is False
        finally:
            db.rollback()


def test_document_archive_requires_not_archived_state():
    with get_db_session() as db:
        try:
            document, _ = create_document_and_version(db)
            repository = DocumentRepository(db)
            repository.archive(
                document.id,
                organization_id=document.organization_id,
            )

            with pytest.raises(ValueError):
                repository.archive(
                    document.id,
                    organization_id=document.organization_id,
                )

        finally:
            db.rollback()


def test_document_unarchive_requires_archived_state():
    with get_db_session() as db:
        try:
            document, _ = create_document_and_version(db)
            repository = DocumentRepository(db)

            with pytest.raises(ValueError):
                repository.unarchive(
                    document.id,
                    organization_id=document.organization_id,
                )

        finally:
            db.rollback()


# ============================================================
# Pending Version Activation Tests
# ============================================================


def test_activate_pending_version_without_previous_active():
    with get_db_session() as db:
        try:
            document, version = create_document_and_version(
                db,
                status="pending",
            )

            version_repo = DocumentVersionRepository(db)

            activated, previous = version_repo.activate_pending_version(
                version.id,
                organization_id=document.organization_id,
            )

            assert activated.id == version.id
            assert activated.status == "active"
            assert previous is None

            active = version_repo.get_active_version(
                document.id,
                organization_id=document.organization_id,
            )

            assert active is not None
            assert active.id == version.id

        finally:
            db.rollback()


def test_change_status_cannot_activate_directly():
    with get_db_session() as db:
        try:
            document, version = create_document_and_version(
                db,
                status="pending",
            )

            with pytest.raises(
                ValueError,
                match="activate_pending_version",
            ):
                DocumentVersionRepository(db).change_status(
                    version.id,
                    "active",
                    organization_id=document.organization_id,
                )
        finally:
            db.rollback()


def test_activate_pending_version_supersedes_previous_active():
    with get_db_session() as db:
        try:
            document, previous_version = create_document_and_version(
                db,
                status="active",
            )

            version_repo = DocumentVersionRepository(db)

            pending_version = version_repo.create(
                document_id=document.id,
                version_number=2,
                original_filename="version_2.pdf",
                storage_key=(
                    f"test/documents/{uuid.uuid4().hex}.pdf"
                ),
                summary="Second version summary.",
                status="pending",
                page_count=8,
                organization_id=document.organization_id,
            )

            activated, previous = version_repo.activate_pending_version(
                pending_version.id,
                organization_id=document.organization_id,
            )

            assert activated.id == pending_version.id
            assert activated.status == "active"

            assert previous is not None
            assert previous.id == previous_version.id
            assert previous.status == "superseded"

            active = version_repo.get_active_version(
                document.id,
                organization_id=document.organization_id,
            )

            assert active is not None
            assert active.id == pending_version.id

        finally:
            db.rollback()


def test_activate_superseded_version_is_rejected():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="superseded",
            )

            version_repo = DocumentVersionRepository(db)

            with pytest.raises(ValueError):
                version_repo.activate_pending_version(
                    version.id,
                    organization_id=version.document.organization_id,
                )

        finally:
            db.rollback()


def test_activate_archived_pending_version_is_rejected():
    with get_db_session() as db:
        try:
            document, version = create_document_and_version(
                db,
                status="pending",
            )

            DocumentRepository(db).archive(
                document.id,
                organization_id=document.organization_id,
            )

            version_repo = DocumentVersionRepository(db)

            with pytest.raises(ValueError):
                version_repo.activate_pending_version(
                    version.id,
                    organization_id=version.document.organization_id,
                )

        finally:
            db.rollback()
