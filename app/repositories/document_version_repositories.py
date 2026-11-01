from datetime import date
from uuid import UUID

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.models.documents import Document
from app.models.document_versions import DocumentVersion

class DocumentVersionRepository:

    VALID_STATUSES = {
        "pending",
        "active",
        "superseded",
    }

    def __init__(self, db: Session):
        self.db = db

    # ================================================
    # CREATE
    # ================================================

    def create(
        self,
        document_id: UUID,
        version_number: int,
        original_filename: str,
        storage_key: str,
        version_label: str | None = None,
        file_hash: str | None = None,
        content_hash: str | None = None,
        summary: str | None = None,
        status: str = "pending",
        effective_from: date | None = None,
        effective_until: date | None = None,
        supersedes_version_id: UUID | None = None,
        page_count: int | None = None,
        version_id: UUID | None = None,
    ) -> DocumentVersion:

        self._validate_status(status)

        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=version_number,
            version_label=version_label,
            original_filename=original_filename,
            storage_key=storage_key,
            file_hash=file_hash,
            content_hash=content_hash,
            summary=summary,
            status=status,
            effective_from=effective_from,
            effective_until=effective_until,
            supersedes_version_id=supersedes_version_id,
            page_count=page_count,
        )

        self.db.add(version)
        self.db.flush()
        self.db.refresh(version)

        return version

    # ================================================
    # READ
    # ================================================

    def get_by_id(
        self,
        version_id: UUID,
    ) -> DocumentVersion | None:

        statement = select(DocumentVersion).where(
            DocumentVersion.id == version_id
        )

        return self.db.scalar(statement)

    def get_by_document(
        self,
        document_id: UUID,
    ) -> list[DocumentVersion]:

        statement = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        )

        return list(self.db.scalars(statement).all())

    def get_active_version(
        self,
        document_id: UUID,
    ) -> DocumentVersion | None:

        statement = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.status == "active",
            DocumentVersion.archived.is_(False),
        )

        return self.db.scalar(statement)

    def get_by_hash(
        self,
        file_hash: str | None = None,
        content_hash: str | None = None,
    ) -> list[DocumentVersion]:

        if not file_hash and not content_hash:
            raise ValueError(
                "Provide at least one hash to search."
            )

        conditions = []

        if file_hash:
            conditions.append(
                DocumentVersion.file_hash == file_hash
            )

        if content_hash:
            conditions.append(
                DocumentVersion.content_hash == content_hash
            )

        statement = (
            select(DocumentVersion)
            .where(or_(*conditions))
            .order_by(DocumentVersion.created_at.desc())
        )

        # Intentionally includes archived versions.
        # Archived documents must still participate in duplicate detection.
        return list(self.db.scalars(statement).all())

    def get_retrieval_eligible_versions(
        self,
        document_id: UUID,
        include_historical: bool = True,
    ) -> list[DocumentVersion]:

        statement = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.archived.is_(False),
        )

        if include_historical:
            statement = statement.where(
                DocumentVersion.status.in_(
                    ["active", "superseded"]
                )
            )
        else:
            statement = statement.where(
                DocumentVersion.status == "active"
            )

        statement = statement.order_by(
            DocumentVersion.version_number.desc()
        )

        return list(self.db.scalars(statement).all())

    # ================================================
    # UPDATE
    # ================================================

    def update(
        self,
        version_id: UUID,
        **kwargs,
    ) -> DocumentVersion | None:

        version = self.get_by_id(version_id)

        if version is None:
            return None

        allowed_fields = {
            "version_label",
            "file_hash",
            "content_hash",
            "summary",
            "effective_from",
            "effective_until",
            "supersedes_version_id",
            "page_count",
            "original_filename",
        }

        invalid_fields = set(kwargs) - allowed_fields

        if invalid_fields:
            raise ValueError(
                f"Invalid version fields: {invalid_fields}"
            )

        for field, value in kwargs.items():
            setattr(version, field, value)

        self.db.flush()
        self.db.refresh(version)

        return version

    # ================================================
    # LIFECYCLE MANAGEMENT
    # ================================================

    def change_status(
        self,
        version_id: UUID,
        status: str,
    ) -> DocumentVersion | None:

        self._validate_status(status)

        version = self.get_by_id(version_id)

        if version is None:
            return None

        version.status = status

        self.db.flush()
        self.db.refresh(version)

        return version

    def archive(
        self,
        version_id: UUID,
    ) -> DocumentVersion | None:

        version = self.get_by_id(version_id)

        if version is None:
            return None

        if version.status == "pending":
            raise ValueError(
                "A pending version cannot be archived."
            )

        if version.archived:
            raise ValueError(
                "This version is already archived."
            )

        version.archived = True

        self.db.flush()
        self.db.refresh(version)

        return version

    def unarchive(
        self,
        version_id: UUID,
        restore_status: str,
    ) -> DocumentVersion | None:

        if restore_status not in {"active", "superseded"}:
            raise ValueError(
                "An archived version can only be restored "
                "as active or superseded."
            )

        version = self.get_by_id(version_id)

        if version is None:
            return None

        if not version.archived:
            raise ValueError(
                "Only archived versions can be unarchived."
            )

        if (
            restore_status == "active"
            and self.get_active_version(version.document_id) is not None
        ):
            raise ValueError(
                "Another active version already exists for this document."
            )

        version.status = restore_status
        version.archived = False

        self.db.flush()
        self.db.refresh(version)

        return version
    
    

    def activate_pending_version(
        self,
        version_id: UUID,
    ) -> tuple[DocumentVersion, DocumentVersion | None] | None:
        """
        Atomically activate a pending document version.
    
        Locks the parent document first to serialize concurrent
        activations for the same document.
    
        Supersedes the previous active version before activating
        the target version to satisfy the partial unique index.
    
        Flushes changes but does not commit.
        The caller owns the outer transaction.
        """
    
        # 1. Read target to identify its parent document.
        target = self.db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id
            )
        )
    
        if target is None:
            return None
    
        document_id = target.document_id
    
        # 2. Lock parent document first.
        document = self.db.scalar(
            select(Document)
            .where(Document.id == document_id)
            .with_for_update()
        )
    
        if document is None:
            raise ValueError(
                f"Parent document not found: {document_id}"
            )
    
        # 3. Lock and reload target version.
        target = self.db.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    
        if target is None:
            return None
    
        # 4. Validate lifecycle state.
        if target.archived:
            raise ValueError(
                "An archived version cannot be activated."
            )
    
        if target.status != "pending":
            raise ValueError(
                f"Only pending versions can be activated. "
                f"Current status: {target.status}"
            )
    
        # 5. Find and lock previous active version.
        previous_active = self.db.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.status == "active",
                DocumentVersion.archived.is_(False),
                DocumentVersion.id != version_id,
            )
            .with_for_update()
        )
    
        # 6. Supersede previous active version and flush first.
        if previous_active is not None:
            previous_active.status = "superseded"
            self.db.flush()
    
        # 7. Activate target only after previous status is persisted.
        target.status = "active"
        self.db.flush()
    
        return target, previous_active
    


    # ================================================
    # DELETE
    # ================================================

    def delete(self, version_id: UUID) -> bool:

        version = self.get_by_id(version_id)

        if version is None:
            return False

        self.db.delete(version)
        self.db.flush()

        return True

    # ================================================
    # VALIDATION
    # ================================================

    @classmethod
    def _validate_status(cls, status: str) -> None:

        if status not in cls.VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. "
                f"Allowed statuses: {sorted(cls.VALID_STATUSES)}"
            )