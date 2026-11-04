from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class OrganizationDepartment(Base):
    __tablename__ = "organization_departments"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_organization_department_org_id",
        ),
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_organization_department_name",
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
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="departments",
    )
    member_assignments: Mapped[list["OrganizationDepartmentMembership"]] = relationship(
        "OrganizationDepartmentMembership",
        back_populates="department",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        primaryjoin=(
            "and_(OrganizationDepartment.id == foreign(Document.department_id), "
            "OrganizationDepartment.organization_id == Document.organization_id)"
        ),
        back_populates="department",
    )
    acl_entries: Mapped[list["DocumentACL"]] = relationship(
        "DocumentACL",
        back_populates="department",
    )

    def __repr__(self) -> str:
        return (
            f"<OrganizationDepartment(id={self.id}, "
            f"organization_id={self.organization_id}, name={self.name!r})>"
        )
