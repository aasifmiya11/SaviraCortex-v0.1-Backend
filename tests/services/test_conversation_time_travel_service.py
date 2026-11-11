from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.models import Conversation, ConversationMessage, ConversationPath
from app.services.conversation_time_travel_service import (
    ConversationTimeTravelError,
    ConversationTimeTravelService,
)


class FakeCheckpointer:
    def __init__(self):
        self.saved = []

    async def aget_tuple(self, config):
        return SimpleNamespace(
            checkpoint={"id": config["configurable"]["checkpoint_id"], "channel_versions": {"messages": 3}},
            metadata={"source": "test"},
        )

    async def aput(self, config, checkpoint, metadata, new_versions):
        self.saved.append((config, checkpoint, metadata, new_versions))
        copied_config = {"configurable": dict(config["configurable"])}
        copied_config["configurable"]["checkpoint_id"] = checkpoint["id"]
        return copied_config


@pytest.fixture
def conversation_history(db_session, organization_context):
    source = Conversation(
        id=uuid4(), organization_id=organization_context["organization"].id,
        user_id=organization_context["owner"].id, title="Original chat", next_sequence=5,
    )
    db_session.add(source)
    db_session.flush()
    rows = [
        ConversationMessage(conversation_id=source.id, sequence=1, role="user", content="First question", request_id=uuid4(), message_metadata={}),
        ConversationMessage(conversation_id=source.id, sequence=2, role="assistant", content="First answer", request_id=uuid4(), message_metadata={"checkpoint_id": "cp-1"}),
        ConversationMessage(conversation_id=source.id, sequence=3, role="user", content="Second question", request_id=uuid4(), message_metadata={}),
        ConversationMessage(conversation_id=source.id, sequence=4, role="assistant", content="Second answer", request_id=uuid4(), message_metadata={"checkpoint_id": "cp-2"}),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return source, rows


@pytest.mark.asyncio
async def test_edit_input_reuses_same_conversation_and_returns_previous_checkpoint(
    db_session, conversation_history, monkeypatch
):
    source, rows = conversation_history
    checkpointer = FakeCheckpointer()
    monkeypatch.setattr("app.services.conversation_time_travel_service.get_checkpointer", lambda: checkpointer)

    result = await ConversationTimeTravelService(db_session).create_branch(
        source_conversation_id=source.id,
        organization_id=source.organization_id,
        user_id=source.user_id,
        action="edit_input",
        target_message_id=rows[2].id,
        edited_query="A revised second question",
    )

    assert result["conversation_id"] == str(source.id)
    assert result["query"] == "A revised second question"
    assert result["parent_checkpoint_id"] == "cp-1"
    assert result["path_group_id"] == str(rows[2].id)
    db_session.refresh(rows[2])
    db_session.refresh(rows[3])
    assert rows[2].message_metadata["path_group_id"] == result["path_group_id"]
    assert rows[3].message_metadata["path_group_id"] == result["path_group_id"]
    assert checkpointer.saved[0][2]["source_thread_id"] == str(source.id)
    copied_snapshot = list(db_session.query(ConversationMessage).filter_by(
        conversation_id=source.id, path_id=UUID(result["path_id"]),
    ).order_by(ConversationMessage.sequence))
    assert copied_snapshot[1].message_metadata["checkpoint_thread_id"] == result["path_id"]
    assert result["path_id"]
    path = db_session.get(ConversationPath, UUID(result["path_id"]))
    snapshot = list(db_session.query(ConversationMessage).filter_by(conversation_id=source.id, path_id=path.id).order_by(ConversationMessage.sequence))
    assert [item.content for item in snapshot] == ["First question", "First answer"]
    assert db_session.query(Conversation).count() == 1
    assert db_session.query(ConversationMessage).filter_by(conversation_id=source.id).count() == 6
    assert path.head_checkpoint_id == "cp-1"
    assert checkpointer.saved[0][0]["configurable"]["thread_id"] == result["path_id"]


@pytest.mark.asyncio
async def test_regenerate_rewinds_same_conversation_without_creating_branch(
    db_session, conversation_history, monkeypatch
):
    source, rows = conversation_history
    checkpointer = FakeCheckpointer()
    monkeypatch.setattr("app.services.conversation_time_travel_service.get_checkpointer", lambda: checkpointer)

    result = await ConversationTimeTravelService(db_session).create_branch(
        source_conversation_id=source.id,
        organization_id=source.organization_id,
        user_id=source.user_id,
        action="regenerate",
        target_message_id=rows[3].id,
    )

    assert result["conversation_id"] == str(source.id)
    assert result["query"] == "Second question"
    assert result["parent_checkpoint_id"] == "cp-1"
    assert result["parent_message_id"] == str(rows[2].id)
    assert result["path_id"]
    path = db_session.get(ConversationPath, UUID(result["path_id"]))
    snapshot = list(db_session.query(ConversationMessage).filter_by(conversation_id=source.id, path_id=path.id).order_by(ConversationMessage.sequence))
    assert [item.content for item in snapshot] == ["First question", "First answer"]
    assert db_session.query(Conversation).count() == 1
    assert db_session.query(ConversationMessage).filter_by(conversation_id=source.id).count() == 6
    assert checkpointer.saved[0][2]["source_checkpoint_id"] == "cp-1"


@pytest.mark.asyncio
async def test_fork_preserves_selected_answer_checkpoint(
    db_session, conversation_history, monkeypatch
):
    source, rows = conversation_history
    checkpointer = FakeCheckpointer()
    monkeypatch.setattr("app.services.conversation_time_travel_service.get_checkpointer", lambda: checkpointer)

    result = await ConversationTimeTravelService(db_session).create_branch(
        source_conversation_id=source.id,
        organization_id=source.organization_id,
        user_id=source.user_id,
        action="fork",
        target_message_id=rows[3].id,
    )

    branch = db_session.get(Conversation, UUID(result["conversation_id"]))
    copied = list(db_session.query(ConversationMessage).filter_by(conversation_id=branch.id).order_by(ConversationMessage.sequence))
    assert result["parent_checkpoint_id"] == "cp-2"
    assert [item.content for item in copied] == ["First question", "First answer", "Second question", "Second answer"]
    assert checkpointer.saved[0][2]["source_checkpoint_id"] == "cp-2"


@pytest.mark.asyncio
async def test_fork_rejects_user_message_without_creating_branch(
    db_session, conversation_history, monkeypatch
):
    source, rows = conversation_history
    monkeypatch.setattr("app.services.conversation_time_travel_service.get_checkpointer", FakeCheckpointer)

    with pytest.raises(ConversationTimeTravelError):
        await ConversationTimeTravelService(db_session).create_branch(
            source_conversation_id=source.id,
            organization_id=source.organization_id,
            user_id=source.user_id,
            action="fork",
            target_message_id=rows[2].id,
        )
    assert db_session.query(Conversation).count() == 1



@pytest.mark.asyncio
async def test_regenerate_from_alternate_answer_uses_original_question_checkpoint(
    db_session, conversation_history, monkeypatch
):
    source, rows = conversation_history
    alternate_path = ConversationPath(
        id=uuid4(), conversation_id=source.id, parent_path_id=None,
        branch_point_message_id=rows[2].id, base_path_id=None,
        fork_checkpoint_id="cp-1", head_checkpoint_id="cp-3", action="regenerate",
    )
    db_session.add(alternate_path)
    db_session.flush()
    prefix = [
        ConversationMessage(conversation_id=source.id, sequence=5, role="user", content="First question",
            request_id=uuid4(), path_id=alternate_path.id, message_metadata={"path_group_id": str(rows[0].id)}),
        ConversationMessage(conversation_id=source.id, sequence=6, role="assistant", content="First answer",
            request_id=uuid4(), path_id=alternate_path.id, message_metadata={"checkpoint_id": "cp-1", "checkpoint_thread_id": str(source.id), "path_group_id": str(rows[0].id)}),
    ]
    duplicate_user = ConversationMessage(
        conversation_id=source.id, sequence=7, role="user", content="Second question",
        request_id=uuid4(), path_id=alternate_path.id, message_metadata={"path_group_id": str(rows[2].id)},
    )
    alternate_answer = ConversationMessage(
        conversation_id=source.id, sequence=8, role="assistant", content="Alternate second answer",
        request_id=uuid4(), path_id=alternate_path.id, message_metadata={"checkpoint_id": "cp-3", "path_group_id": str(rows[2].id)},
    )
    source.next_sequence = 9
    db_session.add_all([*prefix, duplicate_user, alternate_answer])
    db_session.commit()
    checkpointer = FakeCheckpointer()
    monkeypatch.setattr("app.services.conversation_time_travel_service.get_checkpointer", lambda: checkpointer)

    result = await ConversationTimeTravelService(db_session).create_branch(
        source_conversation_id=source.id, organization_id=source.organization_id,
        user_id=source.user_id, action="regenerate", target_message_id=alternate_answer.id,
    )

    assert result["query"] == "Second question"
    assert result["parent_checkpoint_id"] == "cp-1"
    assert result["path_group_id"] == str(rows[2].id)


def test_list_paths_returns_each_regeneration_once_in_creation_order(db_session, conversation_history):
    source, rows = conversation_history
    created_at = datetime(2026, 11, 11, tzinfo=timezone.utc)
    paths = []
    parent_path_id = None
    base_path_id = None

    # Model four consecutive regenerations: v2 is based on v1, v3 on v2, etc.
    for index in range(4):
        path = ConversationPath(
            id=uuid4(),
            conversation_id=source.id,
            parent_path_id=parent_path_id,
            branch_point_message_id=rows[2].id,
            base_path_id=base_path_id,
            fork_checkpoint_id=f"cp-{index}",
            action="regenerate",
            created_at=created_at + timedelta(seconds=index),
        )
        db_session.add(path)
        db_session.flush()
        paths.append(path)
        parent_path_id = path.id
        base_path_id = path.id

    db_session.commit()
    result = ConversationTimeTravelService(db_session).list_paths(
        conversation_id=source.id,
        organization_id=source.organization_id,
        user_id=source.user_id,
        branch_point_message_id=rows[2].id,
    )

    assert [item["path_id"] for item in result["items"]] == [
        None, *(str(path.id) for path in paths)
    ]
    assert len({item["path_id"] for item in result["items"]}) == 5

