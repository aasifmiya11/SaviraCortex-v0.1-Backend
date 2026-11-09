from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class OrganizationRole(Base):
    __tablename__ = "organization_roles"

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name",
            name="uq_organization_role_name",
        ),
        UniqueConstraint(
            "organization_id", "id",
            name="uq_organization_role_org_id",
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
