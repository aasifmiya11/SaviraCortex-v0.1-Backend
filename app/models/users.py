from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Firebase Authentication UID.
    # Nullable while authentication integration is deferred.
    firebase_uid: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        unique=True,
    )

    email: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
        index=True,
    )

    phone_number: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        "OrganizationMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    uploaded_documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="uploaded_by",
        foreign_keys="Document.uploaded_by_user_id",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, firebase_uid={self.firebase_uid!r})>"