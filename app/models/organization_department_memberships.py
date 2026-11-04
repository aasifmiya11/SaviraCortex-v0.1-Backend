from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class OrganizationDepartmentMembership(Base):
    """Many-to-many assignment between an organization member and departments."""

    __tablename__ = "organization_department_memberships"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            ondelete="CASCADE",
            name="fk_department_membership_member",
        ),
        ForeignKeyConstraint(
            ["organization_id", "department_id"],
            [
                "organization_departments.organization_id",
                "organization_departments.id",
            ],
            ondelete="CASCADE",
            name="fk_department_membership_department",
        ),
        Index(
            "idx_department_membership_department",
            "organization_id",
            "department_id",
            "user_id",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, nullable=False
    )
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    membership: Mapped["OrganizationMembership"] = relationship(
        "OrganizationMembership",
        back_populates="department_assignments",
        overlaps="member_assignments",
    )
    department: Mapped["OrganizationDepartment"] = relationship(
        "OrganizationDepartment",
        back_populates="member_assignments",
        overlaps="department_assignments,membership",
    )

    def __repr__(self) -> str:
        return (
            "<OrganizationDepartmentMembership("
            f"organization_id={self.organization_id}, "
            f"user_id={self.user_id}, "
            f"department_id={self.department_id})>"
        )
