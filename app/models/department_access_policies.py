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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class DepartmentAccessPolicy(Base):
    __tablename__ = "department_access_policies"

    __table_args__ = (
        CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="chk_department_policy_effect",
        ),
        UniqueConstraint(
            "organization_id",
            "department",
            "role_id",
            name="uq_department_role_policy",
        ),
        ForeignKeyConstraint(
            ["organization_id", "role_id"],
            [
                "organization_roles.organization_id",
                "organization_roles.id",
            ],
            ondelete="CASCADE",
            name="fk_department_policy_role",
        ),
        Index(
            "idx_department_policy_lookup",
            "organization_id",
            "department",
            "role_id",
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

    department: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
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