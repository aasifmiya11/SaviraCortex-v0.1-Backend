from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class UserRoleAssignment(Base):
    __tablename__ = "user_role_assignments"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            "role_id",
            name="uq_user_organization_role",
        ),
        # A user must be a member of the organization.
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            ondelete="CASCADE",
            name="fk_user_role_assignment_membership",
        ),
        # The assigned role must belong to the same organization.
        ForeignKeyConstraint(
            ["organization_id", "role_id"],
            [
                "organization_roles.organization_id",
                "organization_roles.id",
            ],
            ondelete="CASCADE",
            name="fk_user_role_assignment_role",
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

    role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<UserRoleAssignment("
            f"organization_id={self.organization_id}, "
            f"user_id={self.user_id}, "
            f"role_id={self.role_id})>"
        )