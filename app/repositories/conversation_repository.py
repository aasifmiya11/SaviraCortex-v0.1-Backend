from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Conversation, ConversationMessage


class ConversationNotFoundError(Exception):
    """Raised when a conversation is not owned by the current caller."""


class ConversationRepository:
    """Application-level conversation and paginated message persistence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def fallback_title(first_message: str) -> str:
        normalized = " ".join(first_message.split()).strip(" \t\r\n.,!?;:")
        if not normalized:
            return "New conversation"
        if len(normalized) <= 80:
            return normalized
        truncated = normalized[:77].rsplit(" ", 1)[0].rstrip(".,;:!?")
        return (truncated or normalized[:77]).rstrip() + "…"

    def get_owned(
        self, conversation_id: UUID, organization_id: UUID, user_id: UUID
    ) -> Conversation:
        conversation = self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.organization_id == organization_id,
                Conversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise ConversationNotFoundError
        return conversation

    def find_by_initial_request(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        request_id: UUID,
    ) -> Conversation | None:
        return self.session.scalar(
            select(Conversation).where(
                Conversation.organization_id == organization_id,
                Conversation.user_id == user_id,
                Conversation.creation_request_id == request_id,
            )
        )

    def create_with_user_message(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        request_id: UUID,
        content: str,
    ) -> Conversation:
        conversation = Conversation(
            organization_id=organization_id,
            user_id=user_id,
            title=self.fallback_title(content),
            creation_request_id=request_id,
        )
        try:
            self.session.add(conversation)
            self.session.flush()
            sequence = self._allocate_sequence(conversation.id)
            self.session.add(
                ConversationMessage(
                    conversation_id=conversation.id,
                    sequence=sequence,
                    role="user",
                    content=content,
                    request_id=request_id,
                    message_metadata={},
                )
            )
            self.session.commit()
            self.session.refresh(conversation)
            return conversation
        except IntegrityError:
            self.session.rollback()
            existing = self.find_by_initial_request(
                organization_id=organization_id,
                user_id=user_id,
                request_id=request_id,
            )
            if existing is None:
                raise
            self.append_user_message(
                conversation=existing,
                request_id=request_id,
                content=content,
            )
            return existing

    def append_user_message(
        self,
        *,
        conversation: Conversation,
        request_id: UUID,
        content: str,
        metadata: dict | None = None,
    ) -> ConversationMessage:
        existing = self.session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.request_id == request_id,
                ConversationMessage.role == "user",
            )
        )
        if existing is not None:
            if existing.content != content:
                raise ValueError("The request ID was already used for a different message.")
            if metadata:
                existing.message_metadata = {**(existing.message_metadata or {}), **metadata}
                self.session.commit()
                self.session.refresh(existing)
            return existing

        sequence = self._allocate_sequence(conversation.id)
        message = ConversationMessage(
            conversation_id=conversation.id,
            sequence=sequence,
            role="user",
            content=content,
            request_id=request_id,
            message_metadata=metadata or {},
        )
        self.session.add(message)
        try:
            self.session.commit()
            self.session.refresh(message)
            return message
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == conversation.id,
                    ConversationMessage.request_id == request_id,
                    ConversationMessage.role == "user",
                )
            )
            if existing is None or existing.content != content:
                raise
            return existing

    def get_assistant_response(
        self, conversation_id: UUID, request_id: UUID
    ) -> dict | None:
        message = self.session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.request_id == request_id,
                ConversationMessage.role == "assistant",
            )
        )
        return dict(message.message_metadata or {}) if message else None

    def append_assistant_message(
        self,
        *,
        conversation: Conversation,
        request_id: UUID,
        content: str,
        metadata: dict,
    ) -> ConversationMessage:
        existing = self.session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.request_id == request_id,
                ConversationMessage.role == "assistant",
            )
        )
        if existing is not None:
            return existing

        sequence = self._allocate_sequence(conversation.id)
        message = ConversationMessage(
            conversation_id=conversation.id,
            sequence=sequence,
            role="assistant",
            content=content,
            request_id=request_id,
            message_metadata=metadata,
        )
        self.session.add(message)
        try:
            self.session.commit()
            self.session.refresh(message)
            return message
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == conversation.id,
                    ConversationMessage.request_id == request_id,
                    ConversationMessage.role == "assistant",
                )
            )
            if existing is None:
                raise
            return existing

    def _allocate_sequence(self, conversation_id: UUID) -> int:
        """Atomically reserve a sequence number while serializing writes per chat."""
        next_sequence = self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                next_sequence=Conversation.next_sequence + 1,
                updated_at=func.now(),
            )
            .returning(Conversation.next_sequence - 1)
        ).scalar_one()
        return int(next_sequence)

    def list_for_user(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Conversation], int]:
        statement = (
            select(Conversation)
            .where(
                Conversation.organization_id == organization_id,
                Conversation.user_id == user_id,
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list(self.session.scalars(statement).all())
        total = self.session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.organization_id == organization_id,
                Conversation.user_id == user_id,
            )
        ) or 0
        return items, int(total)

    def list_messages(
        self,
        *,
        conversation_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationMessage], int]:
        statement = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.sequence.desc())
            .limit(limit)
            .offset(offset)
        )
        newest_first = list(self.session.scalars(statement).all())
        items = list(reversed(newest_first))
        total = self.session.scalar(
            select(func.count())
            .select_from(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
        ) or 0
        return items, int(total)

    def rename(self, conversation: Conversation, title: str) -> Conversation:
        conversation.title = title.strip()
        conversation.title_is_user_edited = True
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    def delete(self, conversation: Conversation) -> None:
        self.session.delete(conversation)
        self.session.commit()
