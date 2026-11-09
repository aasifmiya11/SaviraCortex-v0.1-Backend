from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class GenerationFeedback(Base):
    """Persist RAG examples and human relevance labels for evaluation datasets."""

    __tablename__ = "generation_feedback"
    __table_args__ = (
        CheckConstraint(
            "feedback_status IS NULL OR feedback_status IN ('relevant', 'not_relevant')",
            name="chk_generation_feedback_status",
        ),
        Index(
            "idx_generation_feedback_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "idx_generation_feedback_org_label",
            "organization_id",
            "feedback_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    generated_queries: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    generated_query_count: Mapped[int] = mapped_column(
        nullable=False, default=0
    )
    retrieval_trace: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    retrieved_documents: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    answer_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    answer_status: Mapped[str] = mapped_column(String(40), nullable=False)
    feedback_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    feedback_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
