from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    DDL,
    ForeignKey,
    Index,
    JSON,
    String,
    Uuid,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class OrganizationInvitation(Base):
    """A single-use invitation that exists before the candidate creates an account."""

    __tablename__ = "organization_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked')",
            name="chk_organization_invitation_status",
        ),
        CheckConstraint(
            "invited_role IN ('admin', 'member')",
            name="chk_organization_invitation_role",
        ),
        Index("ix_org_invitations_org_status", "organization_id", "status"),
        Index("ix_org_invitations_expiry", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    invited_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    candidate_name: Mapped[str] = mapped_column(String(255), nullable=False)
    invited_role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member", server_default="member"
    )
    assigned_role_ids: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list, server_default="[]"
    )
    assigned_department_ids: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list, server_default="[]"
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


event.listen(
    OrganizationInvitation.__table__,
    "after_create",
    DDL(
        """
        CREATE OR REPLACE FUNCTION cleanup_expired_organization_invitations()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            DELETE FROM organization_invitations
            WHERE expires_at <= CURRENT_TIMESTAMP;
            RETURN NULL;
        END;
        $$;
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    OrganizationInvitation.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER trg_cleanup_expired_organization_invitations
        AFTER INSERT OR UPDATE ON organization_invitations
        FOR EACH STATEMENT
        EXECUTE FUNCTION cleanup_expired_organization_invitations()
        """
    ).execute_if(dialect="postgresql"),
)
