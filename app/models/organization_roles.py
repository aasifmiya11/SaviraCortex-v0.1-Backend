from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class OrganizationRole(Base):
    __tablename__ = "organization_roles"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_organization_role_name",
        ),
        # Required as a composite FK target in other tables.
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_organization_role_org_id",
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

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<OrganizationRole("
            f"id={self.id}, "
            f"organization_id={self.organization_id}, "
            f"name={self.name!r})>"
        )