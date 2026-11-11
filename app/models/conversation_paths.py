from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class ConversationPath(Base):
    __tablename__ = "conversation_paths"
    __table_args__ = (
        Index("idx_conversation_paths_branch_point", "conversation_id", "branch_point_message_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    parent_path_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversation_paths.id", ondelete="SET NULL"), nullable=True
    )
    branch_point_message_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    base_path_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    fork_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    head_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation")
