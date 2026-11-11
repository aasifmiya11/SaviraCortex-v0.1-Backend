from __future__ import annotations

from copy import deepcopy
import logging
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.checkpointer import get_checkpointer
from app.models import Conversation, ConversationMessage, ConversationPath
from app.repositories.conversation_repository import ConversationNotFoundError

logger = logging.getLogger(__name__)


class ConversationTimeTravelError(Exception):
    """A requested time-travel operation cannot be safely completed."""


class ConversationTimeTravelService:
    """Persist complete, isolated timelines inside one conversation identity."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.checkpointer = get_checkpointer()

    def _owned_conversation(self, conversation_id: UUID, organization_id: UUID, user_id: UUID) -> Conversation:
        item = self.session.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.organization_id == organization_id, Conversation.user_id == user_id,
        ))
        if item is None:
            raise ConversationNotFoundError
        return item

    def _message(self, conversation_id: UUID, message_id: UUID) -> ConversationMessage:
        item = self.session.scalar(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id, ConversationMessage.id == message_id,
        ))
        if item is None:
            raise ConversationNotFoundError
        return item

    @staticmethod
    def _thread_id(conversation_id: UUID, path_id: UUID | None) -> str:
        return str(path_id or conversation_id)

    async def _copy_checkpoint(self, source_thread_id: str, checkpoint_id: str | None, destination_thread_id: str) -> str | None:
        if not checkpoint_id:
            return None
        config = {"configurable": {"thread_id": source_thread_id, "checkpoint_id": str(checkpoint_id)}}
        checkpoint_tuple = await self.checkpointer.aget_tuple(config)
        if checkpoint_tuple is None:
            raise ConversationTimeTravelError("The selected checkpoint is no longer available.")
        source_cfg = (getattr(checkpoint_tuple, "config", None) or {}).get("configurable", {})
        # AsyncPostgresSaver.aput requires checkpoint_ns even for the root
        # namespace, which LangGraph represents as an empty string.
        configurable = {
            "thread_id": destination_thread_id,
            "checkpoint_ns": source_cfg.get("checkpoint_ns") or "",
        }
        checkpoint = deepcopy(checkpoint_tuple.checkpoint)
        metadata = deepcopy(checkpoint_tuple.metadata or {})
        metadata.update({"source_thread_id": source_thread_id, "source_checkpoint_id": str(checkpoint_id)})
        copied_config = await self.checkpointer.aput(
            {"configurable": configurable}, checkpoint, metadata, deepcopy(checkpoint.get("channel_versions", {})),
        )
        if not copied_config or await self.checkpointer.aget_tuple(copied_config) is None:
            raise RuntimeError("The copied checkpoint could not be read back from its destination thread.")
        return str(copied_config.get("configurable", {}).get("checkpoint_id"))

    def _path_messages(self, conversation_id: UUID, path_id: UUID | None) -> list[ConversationMessage]:
        return list(self.session.scalars(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id, ConversationMessage.path_id == path_id,
        ).order_by(ConversationMessage.sequence.asc())).all())

    async def create_branch(
        self, *, source_conversation_id: UUID, organization_id: UUID, user_id: UUID,
        action: str, target_message_id: UUID, edited_query: str | None = None,
    ) -> dict:
        if self.checkpointer is None:
            raise ConversationTimeTravelError("Conversation checkpoint storage is unavailable.")
        source = self._owned_conversation(source_conversation_id, organization_id, user_id)
        target = self._message(source.id, target_message_id)
        source_path_id = target.path_id
        messages = self._path_messages(source.id, source_path_id)
        try:
            target_index = next(i for i, item in enumerate(messages) if item.id == target.id)
        except StopIteration as exc:
            raise ConversationNotFoundError from exc

        if action in {"regenerate", "edit_input"}:
            if action == "edit_input" and target.role != "user":
                raise ConversationTimeTravelError("Editing requires a user message.")
            if action == "regenerate" and target.role != "assistant":
                raise ConversationTimeTravelError("Regeneration must target an assistant answer.")
            user_index = target_index if target.role == "user" else next(
                (i for i in range(target_index - 1, -1, -1) if messages[i].role == "user"), -1
            )
            if user_index < 0:
                raise ConversationTimeTravelError("The original user question could not be found on this timeline.")
            user_message = messages[user_index]
            query = (edited_query or "").strip() if action == "edit_input" else user_message.content
            if not query:
                raise ConversationTimeTravelError("The edited question cannot be empty.")
            previous_assistant = next((item for item in reversed(messages[:user_index]) if item.role == "assistant"), None)
            previous_metadata = previous_assistant.message_metadata or {} if previous_assistant else {}
            checkpoint_id = previous_metadata.get("checkpoint_id") if previous_assistant else None
            checkpoint_source_thread_id = previous_metadata.get("checkpoint_thread_id") or self._thread_id(source.id, source_path_id)
            if previous_assistant is not None and not checkpoint_id:
                raise ConversationTimeTravelError("The preceding answer has no saved checkpoint, so this point cannot be resumed safely.")
            # Canonical ID stays stable across copies so all versions share one selector.
            group_id = UUID(str((user_message.message_metadata or {}).get("path_group_id") or user_message.id))

            # Keep the original answer in the same version group as every
            # regenerated answer. Otherwise the controls disappear when the
            # user switches back to the original timeline.
            original_answer = target if target.role == "assistant" else next(
                (item for item in messages[user_index + 1:] if item.role == "assistant"),
                None,
            )
            user_metadata = deepcopy(user_message.message_metadata or {})
            user_metadata["path_group_id"] = str(group_id)
            user_message.message_metadata = user_metadata
            if original_answer is not None:
                answer_metadata = deepcopy(original_answer.message_metadata or {})
                answer_metadata["path_group_id"] = str(group_id)
                original_answer.message_metadata = answer_metadata

            path = ConversationPath(
                id=uuid4(), conversation_id=source.id, parent_path_id=source_path_id,
                branch_point_message_id=group_id, base_path_id=source_path_id,
                fork_checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
                action=action,
            )
            self.session.add(path)
            self.session.flush()
            prefix = messages[:user_index]
            active_group_id = None
            boundary_copy = None
            for item in prefix:
                metadata = deepcopy(item.message_metadata or {})
                if item.role == "assistant" and metadata.get("checkpoint_id"):
                    metadata.setdefault("checkpoint_thread_id", self._thread_id(source.id, source_path_id))
                if item.role == "user":
                    active_group_id = str(metadata.get("path_group_id") or item.id)
                    metadata["path_group_id"] = active_group_id
                elif active_group_id:
                    metadata.setdefault("path_group_id", active_group_id)
                copied_message = ConversationMessage(
                    conversation_id=source.id, sequence=self._next_sequence(source.id), role=item.role,
                    content=item.content, request_id=uuid4(), path_id=path.id, message_metadata=metadata,
                )
                self.session.add(copied_message)
                if previous_assistant is not None and item.id == previous_assistant.id:
                    boundary_copy = copied_message
            self.session.commit()
            try:
                copied_checkpoint_id = await self._copy_checkpoint(
                    checkpoint_source_thread_id, str(checkpoint_id) if checkpoint_id else None, str(path.id),
                )
                path.head_checkpoint_id = copied_checkpoint_id
                if boundary_copy is not None and copied_checkpoint_id:
                    boundary_copy.message_metadata = {
                        **(boundary_copy.message_metadata or {}),
                        "checkpoint_id": copied_checkpoint_id,
                        "checkpoint_thread_id": str(path.id),
                    }
                self.session.commit()
            except Exception as exc:
                logger.exception("Failed to initialize timeline %s from checkpoint %s.", path.id, checkpoint_id)
                self.session.delete(path)
                self.session.commit()
                raise ConversationTimeTravelError("The selected checkpoint could not be copied into this timeline.") from exc
            return {
                "conversation_id": str(source.id), "path_id": str(path.id),
                "parent_path_id": str(source_path_id) if source_path_id else None,
                "parent_checkpoint_id": copied_checkpoint_id, "source_checkpoint_id": str(checkpoint_id) if checkpoint_id else None,
                "parent_message_id": str(user_message.id), "path_group_id": str(group_id),
                "query": query, "branch_action": action, "title": source.title,
            }

        if action == "fork":
            if target.role != "assistant":
                raise ConversationTimeTravelError("Fork must target an assistant answer.")
            target_metadata = target.message_metadata or {}
            checkpoint_id = target_metadata.get("checkpoint_id")
            checkpoint_source_thread_id = target_metadata.get("checkpoint_thread_id") or self._thread_id(source.id, source_path_id)
            if not checkpoint_id:
                raise ConversationTimeTravelError("This answer has no saved checkpoint to fork from.")
            branch = Conversation(
                organization_id=organization_id, user_id=user_id, title=(f"Fork: {source.title}")[:255],
                creation_request_id=uuid4(), parent_conversation_id=source.id, parent_message_id=target.id,
                parent_checkpoint_id=str(checkpoint_id), branch_action="fork",
            )
            self.session.add(branch)
            self.session.flush()
            target_copy = None
            for item in messages[:target_index + 1]:
                metadata = deepcopy(item.message_metadata or {})
                if item.role == "assistant" and metadata.get("checkpoint_id"):
                    metadata.setdefault("checkpoint_thread_id", self._thread_id(source.id, source_path_id))
                metadata["branched_from_message_id"] = str(item.id)
                copied_message = ConversationMessage(
                    conversation_id=branch.id, sequence=self._next_sequence(branch.id), role=item.role,
                    content=item.content, request_id=uuid4(), message_metadata=metadata,
                )
                self.session.add(copied_message)
                if item.id == target.id:
                    target_copy = copied_message
            self.session.commit()
            try:
                copied_checkpoint_id = await self._copy_checkpoint(checkpoint_source_thread_id, str(checkpoint_id), str(branch.id))
                if target_copy is not None and copied_checkpoint_id:
                    target_copy.message_metadata = {
                        **(target_copy.message_metadata or {}),
                        "checkpoint_id": copied_checkpoint_id,
                        "checkpoint_thread_id": str(branch.id),
                    }
                    self.session.commit()
            except Exception as exc:
                logger.exception("Failed to fork conversation %s at checkpoint %s.", source.id, checkpoint_id)
                self.session.delete(branch)
                self.session.commit()
                raise ConversationTimeTravelError("The selected checkpoint could not be copied into the new conversation.") from exc
            return {
                "conversation_id": str(branch.id), "parent_conversation_id": str(source.id),
                "parent_checkpoint_id": str(checkpoint_id), "parent_message_id": str(target.id),
                "branch_action": "fork", "title": branch.title,
            }
        raise ConversationTimeTravelError("Unsupported time-travel action.")

    def _next_sequence(self, conversation_id: UUID) -> int:
        from sqlalchemy import update, func
        return int(self.session.execute(
            update(Conversation).where(Conversation.id == conversation_id)
            .values(next_sequence=Conversation.next_sequence + 1, updated_at=func.now())
            .returning(Conversation.next_sequence - 1)
        ).scalar_one())

    def list_paths(self, *, conversation_id: UUID, organization_id: UUID, user_id: UUID, branch_point_message_id: UUID) -> dict:
        self._owned_conversation(conversation_id, organization_id, user_id)
        paths = list(self.session.scalars(select(ConversationPath).where(
            ConversationPath.conversation_id == conversation_id,
            ConversationPath.branch_point_message_id == branch_point_message_id,
        ).order_by(ConversationPath.created_at.asc(), ConversationPath.id.asc())).all())
        # Each regeneration stores the timeline it was created from in base_path_id.
        # Including every distinct base id as well as every path duplicates earlier
        # versions (for example: original, v1, v2, v1, v2, v3), which breaks Previous/Next.
        # The oldest path's base is the single original timeline; each path row is
        # then one distinct regenerated version in creation order.
        base_path_id = paths[0].base_path_id if paths else None
        versions = [{
            "path_id": str(base_path_id) if base_path_id else None,
            "label": "Original" if base_path_id is None else "Parent timeline",
            "created_at": None,
        }]
        versions.extend(
            {"path_id": str(item.id), "label": "Version", "created_at": item.created_at}
            for item in paths
        )
        return {"branch_point_message_id": str(branch_point_message_id), "items": versions}
