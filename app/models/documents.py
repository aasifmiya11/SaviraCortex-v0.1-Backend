from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    and_,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from ..core.database import Base


def _department_join():
    from .organization_departments import OrganizationDepartment

    return and_(
        OrganizationDepartment.id == foreign(Document.department_id),
        OrganizationDepartment.organization_id == Document.organization_id,
    )


class Document(Base):
    __tablename__ = "documents"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_documents_organization_id",
        ),
        ForeignKeyConstraint(
            ["organization_id", "department_id"],
            [
                "organization_departments.organization_id",
                "organization_departments.id",
            ],
            ondelete="NO ACTION",
            name="fk_document_department",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    document_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Authoritative department assignment.
    department_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    organization_wide_access: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="documents",
    )

    uploaded_by: Mapped["User | None"] = relationship(
        "User",
        back_populates="uploaded_documents",
        foreign_keys=[uploaded_by_user_id],
    )

    department: Mapped["OrganizationDepartment | None"] = relationship(
        "OrganizationDepartment",
        primaryjoin=_department_join,
        back_populates="documents",
    )

    versions: Mapped[list["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="save-update, merge",
    )

    def __repr__(self) -> str:
        return (
            f"<Document("
            f"id={self.id}, "
            f"organization_id={self.organization_id}, "
            f"title={self.title!r}, "
            f"department_id={self.department_id}, "
            f"archived={self.archived})>"
        )