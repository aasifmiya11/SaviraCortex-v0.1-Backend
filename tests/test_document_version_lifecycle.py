
import uuid

import pytest

from app.core.database import get_db_session
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

    document = document_repo.create(
        title=f"Lifecycle Test Document {unique_id}",
        document_type="Policy",
        department="Testing",
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
    )

    return document, version


def test_new_version_defaults_to_not_archived():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(db)

            assert version.archived is False
            assert version.status == "pending"

        finally:
            db.rollback()


def test_archive_preserves_active_status():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="active",
            )

            version_repo = DocumentVersionRepository(db)

            archived_version = version_repo.archive(version.id)

            assert archived_version is not None
            assert archived_version.archived is True
            assert archived_version.status == "active"

            assert version_repo.get_active_version(
                version.document_id
            ) is None

        finally:
            db.rollback()


def test_archive_preserves_superseded_status():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="superseded",
            )

            version_repo = DocumentVersionRepository(db)

            archived_version = version_repo.archive(version.id)

            assert archived_version.archived is True
            assert archived_version.status == "superseded"

        finally:
            db.rollback()


def test_pending_version_cannot_be_archived():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="pending",
            )

            version_repo = DocumentVersionRepository(db)

            with pytest.raises(ValueError):
                version_repo.archive(version.id)

        finally:
            db.rollback()


def test_cannot_archive_twice():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="active",
            )

            version_repo = DocumentVersionRepository(db)

            version_repo.archive(version.id)

            with pytest.raises(ValueError):
                version_repo.archive(version.id)

        finally:
            db.rollback()


def test_unarchive_as_superseded():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="superseded",
            )

            version_repo = DocumentVersionRepository(db)

            version_repo.archive(version.id)

            restored = version_repo.unarchive(
                version.id,
                restore_status="superseded",
            )

            assert restored.archived is False
            assert restored.status == "superseded"

        finally:
            db.rollback()


def test_unarchive_as_active_when_no_active_version_exists():
    with get_db_session() as db:
        try:
            document, version = create_document_and_version(
                db,
                status="active",
            )

            version_repo = DocumentVersionRepository(db)

            version_repo.archive(version.id)

            restored = version_repo.unarchive(
                version.id,
                restore_status="active",
            )

            assert restored.archived is False
            assert restored.status == "active"

            active = version_repo.get_active_version(document.id)

            assert active is not None
            assert active.id == version.id

        finally:
            db.rollback()


def test_cannot_unarchive_as_active_if_another_active_exists():
    with get_db_session() as db:
        try:
            document, first_version = create_document_and_version(
                db,
                status="active",
            )

            version_repo = DocumentVersionRepository(db)

            version_repo.archive(first_version.id)

            second_version = version_repo.create(
                document_id=document.id,
                version_number=2,
                original_filename="second_version.pdf",
                storage_key=(
                    f"test/documents/{uuid.uuid4().hex}.pdf"
                ),
                summary="Second version.",
                status="active",
                page_count=5,
            )

            with pytest.raises(ValueError):
                version_repo.unarchive(
                    first_version.id,
                    restore_status="active",
                )

            current_active = version_repo.get_active_version(
                document.id
            )

            assert current_active is not None
            assert current_active.id == second_version.id

        finally:
            db.rollback()


def test_archived_versions_are_excluded_from_retrieval():
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
                storage_key=(
                    f"test/documents/{uuid.uuid4().hex}.pdf"
                ),
                summary="Historical version.",
                status="superseded",
                page_count=5,
            )

            version_repo.archive(historical_version.id)

            all_eligible = version_repo.get_retrieval_eligible_versions(
                document.id,
                include_historical=True,
            )

            active_only = version_repo.get_retrieval_eligible_versions(
                document.id,
                include_historical=False,
            )

            assert len(all_eligible) == 1
            assert all_eligible[0].id == active_version.id

            assert len(active_only) == 1
            assert active_only[0].id == active_version.id

        finally:
            db.rollback()


def test_archived_versions_are_included_in_hash_matching():
    with get_db_session() as db:
        try:
            file_hash = uuid.uuid4().hex
            content_hash = uuid.uuid4().hex

            _, version = create_document_and_version(
                db,
                status="active",
                file_hash=file_hash,
                content_hash=content_hash,
            )

            version_repo = DocumentVersionRepository(db)

            version_repo.archive(version.id)

            matches = version_repo.get_by_hash(
                file_hash=file_hash,
                content_hash=content_hash,
            )

            assert len(matches) == 1
            assert matches[0].id == version.id
            assert matches[0].archived is True

        finally:
            db.rollback()


def test_invalid_restore_status_is_rejected():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="superseded",
            )

            version_repo = DocumentVersionRepository(db)

            version_repo.archive(version.id)

            with pytest.raises(ValueError):
                version_repo.unarchive(
                    version.id,
                    restore_status="pending",
                )

        finally:
            db.rollback()


def test_cannot_unarchive_non_archived_version():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="superseded",
            )

            version_repo = DocumentVersionRepository(db)

            with pytest.raises(ValueError):
                version_repo.unarchive(
                    version.id,
                    restore_status="superseded",
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
                version.id
            )

            assert activated.id == version.id
            assert activated.status == "active"
            assert activated.archived is False
            assert previous is None

            active = version_repo.get_active_version(document.id)

            assert active is not None
            assert active.id == version.id

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
            )

            activated, previous = version_repo.activate_pending_version(
                pending_version.id
            )

            assert activated.id == pending_version.id
            assert activated.status == "active"

            assert previous is not None
            assert previous.id == previous_version.id
            assert previous.status == "superseded"

            active = version_repo.get_active_version(document.id)

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
                version_repo.activate_pending_version(version.id)

        finally:
            db.rollback()


def test_activate_archived_pending_version_is_rejected():
    with get_db_session() as db:
        try:
            _, version = create_document_and_version(
                db,
                status="pending",
            )

            version.archived = True
            db.flush()

            version_repo = DocumentVersionRepository(db)

            with pytest.raises(ValueError):
                version_repo.activate_pending_version(version.id)

        finally:
            db.rollback()
