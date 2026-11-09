from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class OrganizationDepartment(Base):
    __tablename__ = "organization_departments"

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name",
            name="uq_organization_department_name",
        ),
        UniqueConstraint(
            "organization_id", "id",
            name="uq_organization_department_org_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="departments"
    )
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
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
        "DocumentACL", back_populates="department"
    )
