from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class DocumentACL(Base):
    __tablename__ = "document_acl"

    __table_args__ = (
        CheckConstraint(
            """
            (
                principal_type = 'user'
                AND user_id IS NOT NULL
                AND role_id IS NULL
                AND department_id IS NULL
            )
            OR
            (
                principal_type = 'role'
                AND role_id IS NOT NULL
                AND user_id IS NULL
                AND department_id IS NULL
            )
            OR
            (
                principal_type = 'department'
                AND department_id IS NOT NULL
                AND user_id IS NULL
                AND role_id IS NULL
            )
            """,
            name="chk_document_acl_principal",
        ),
        CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="chk_document_acl_effect",
        ),
        ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["documents.organization_id", "documents.id"],
            ondelete="CASCADE",
            name="fk_document_acl_document",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            ondelete="CASCADE",
            name="fk_document_acl_user_membership",
        ),
        ForeignKeyConstraint(
            ["organization_id", "role_id"],
            [
                "organization_roles.organization_id",
                "organization_roles.id",
            ],
            ondelete="CASCADE",
            name="fk_document_acl_role",
        ),
        ForeignKeyConstraint(
            ["organization_id", "department_id"],
            [
                "organization_departments.organization_id",
                "organization_departments.id",
            ],
            ondelete="CASCADE",
            name="fk_document_acl_department",
        ),
        Index(
            "idx_document_acl_document",
            "organization_id",
            "document_id",
        ),
        Index(
            "idx_document_acl_user",
            "organization_id",
            "user_id",
        ),
        Index(
            "idx_document_acl_role",
            "organization_id",
            "role_id",
        ),
        Index(
            "idx_document_acl_department",
            "organization_id",
            "department_id",
        ),
        Index(
            "uq_document_acl_user",
            "organization_id",
            "document_id",
            "user_id",
            "effect",
            unique=True,
            postgresql_where=text("principal_type = 'user'"),
        ),
        Index(
            "uq_document_acl_role",
            "organization_id",
            "document_id",
            "role_id",
            "effect",
            unique=True,
            postgresql_where=text("principal_type = 'role'"),
        ),
        Index(
            "uq_document_acl_department",
            "organization_id",
            "document_id",
            "department_id",
            "effect",
            unique=True,
            postgresql_where=text("principal_type = 'department'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )

    principal_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )

    role_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )

    department_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )

    effect: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="acl_entries",
        overlaps="acl_entries",
    )

    department: Mapped["OrganizationDepartment | None"] = relationship(
        "OrganizationDepartment",
        back_populates="acl_entries",
        overlaps="acl_entries,document",
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentACL("
            f"organization_id={self.organization_id}, "
            f"document_id={self.document_id}, "
            f"principal_type={self.principal_type!r}, "
            f"effect={self.effect!r})>"
        )