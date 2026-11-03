from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    and_,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from ..core.database import Base


def _department_join():
    from .organization_departments import OrganizationDepartment

    return and_(
        OrganizationDepartment.id
        == foreign(OrganizationMembership.department_id),
        OrganizationDepartment.organization_id
        == OrganizationMembership.organization_id,
    )


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"

    __table_args__ = (
    UniqueConstraint(
        "organization_id",
        "user_id",
        name="uq_organization_membership",
    ),
    CheckConstraint(
        "role IN ('owner', 'admin', 'member')",
        name="chk_organization_membership_role",
    ),
    ForeignKeyConstraint(
        ["organization_id", "department_id"],
        [
            "organization_departments.organization_id",
            "organization_departments.id",
        ],
        ondelete="NO ACTION",
        name="fk_membership_department",
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

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    department_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="member",
        server_default="member",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="memberships",
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="memberships",
    )

    department: Mapped["OrganizationDepartment | None"] = relationship(
        "OrganizationDepartment",
        primaryjoin=_department_join,
        back_populates="memberships",
    )

    def __repr__(self) -> str:
        return (
            f"<OrganizationMembership("
            f"organization_id={self.organization_id}, "
            f"user_id={self.user_id}, "
            f"department_id={self.department_id}, "
            f"role={self.role!r})>"
        )