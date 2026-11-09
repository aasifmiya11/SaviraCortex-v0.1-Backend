
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import Document


class DocumentRepository:

    def __init__(self, db: Session):
        self.db = db

    # ================================================
    # CREATE
    # ================================================

    def create(
        self,
        title: str,
        document_type: str,
        organization_id: UUID,
        description: str | None = None,
        uploaded_by_user_id: UUID | None = None,
        document_id: UUID | None = None,
        archived: bool = False,
    ) -> Document:

        document = Document(
            id=document_id,
            organization_id=organization_id,
            uploaded_by_user_id=uploaded_by_user_id,
            title=title,
            document_type=document_type,
            description=description,
            archived=archived,
        )
    
        self.db.add(document)
        self.db.flush()
        self.db.refresh(document)
    
        return document

    # ================================================
    # READ
    # ================================================

    def get_by_id(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
    ) -> Document | None:

        statement = select(Document).where(
            Document.id == document_id,
            Document.organization_id == organization_id,
        )

        return self.db.scalar(statement)

    def get_by_title(
        self,
        title: str,
        *,
        organization_id: UUID,
    ) -> list[Document]:

        statement = (
            select(Document)
            .where(
                Document.title.ilike(title),
                Document.organization_id == organization_id,
            )
            .order_by(Document.created_at.desc())
        )

        return list(self.db.scalars(statement).all())

    def get_all(
        self,
        department_id: UUID | None = None,
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        organization_id: UUID,
    ) -> list[Document]:

        statement = select(Document).where(
            Document.organization_id == organization_id
        )

        if department_id is not None:
            from app.models.document_acl import DocumentACL
            statement = statement.where(
                Document.id.in_(
                    select(DocumentACL.document_id).where(
                        DocumentACL.organization_id == organization_id,
                        DocumentACL.principal_type == "department",
                        DocumentACL.department_id == department_id,
                        DocumentACL.effect == "allow",
                    )
                )
            )

        if document_type:
            statement = statement.where(
                Document.document_type == document_type
            )

        statement = (
            statement
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        return list(self.db.scalars(statement).all())

    # ================================================
    # UPDATE
    # ================================================

    def update(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
        **kwargs,
    ) -> Document | None:

        document = self.get_by_id(
            document_id,
            organization_id=organization_id,
        )

        if document is None:
            return None

        allowed_fields = {
            "title",
            "document_type",
            "description",
        }

        invalid_fields = set(kwargs) - allowed_fields

        if invalid_fields:
            raise ValueError(
                f"Invalid document fields: {invalid_fields}"
            )

        for field, value in kwargs.items():
            setattr(document, field, value)

        self.db.flush()
        self.db.refresh(document)

        return document

    def archive(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
    ) -> Document | None:
        document = self.get_by_id(
            document_id,
            organization_id=organization_id,
        )
        if document is None:
            return None
        if document.archived:
            raise ValueError("This document is already archived.")

        document.archived = True
        self.db.flush()
        self.db.refresh(document)
        return document

    def unarchive(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
    ) -> Document | None:
        document = self.get_by_id(
            document_id,
            organization_id=organization_id,
        )
        if document is None:
            return None
        if not document.archived:
            raise ValueError("This document is not archived.")

        document.archived = False
        self.db.flush()
        self.db.refresh(document)
        return document

    # ================================================
    # DELETE
    # ================================================

    def delete(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
    ) -> bool:

        document = self.get_by_id(
            document_id,
            organization_id=organization_id,
        )

        if document is None:
            return False

        if document.versions:
            raise ValueError(
                "Cannot delete a document that has versions. "
                "Handle its versions explicitly first."
            )

        self.db.delete(document)
        self.db.flush()

        return True
