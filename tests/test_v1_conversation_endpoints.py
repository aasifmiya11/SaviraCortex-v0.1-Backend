from uuid import uuid4

import pytest

from app.api.v1.endpoints.conversations import get_checkpointer
from app.models import Conversation, ConversationMessage


class FakeCheckpointer:
    def __init__(self):
        self.deleted_threads = []

    async def adelete_thread(self, thread_id):
        self.deleted_threads.append(thread_id)


def _conversation_with_messages(db_session, organization_id, user_id, count=25):
    conversation = Conversation(
        id=uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        title="Initial conversation title",
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add_all(
        [
            ConversationMessage(
                conversation_id=conversation.id,
                sequence=index,
                role="user" if index % 2 else "assistant",
                content=f"Message {index}",
                message_metadata={},
            )
            for index in range(1, count + 1)
        ]
    )
    db_session.commit()
    return conversation


def test_member_can_list_conversations(client, db_session, organization_context):
    conversation = _conversation_with_messages(
        db_session,
        organization_context["organization"].id,
        organization_context["owner"].id,
    )

    response = client.get(
        f"/api/v1/organizations/{organization_context['organization'].id}/conversations"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["conversation_id"] == str(conversation.id)
    assert payload["items"][0]["title"] == "Initial conversation title"


def test_message_history_returns_latest_page_and_older_offset_page(
    client, db_session, organization_context
):
    conversation = _conversation_with_messages(
        db_session,
        organization_context["organization"].id,
        organization_context["owner"].id,
    )
    route = (
        f"/api/v1/organizations/{organization_context['organization'].id}"
        f"/conversations/{conversation.id}/messages"
    )

    latest = client.get(route, params={"limit": 20, "offset": 0})
    assert latest.status_code == 200
    latest_payload = latest.json()
    assert latest_payload["total"] == 25
    assert latest_payload["has_more"] is True
    assert [item["sequence"] for item in latest_payload["items"]] == list(range(6, 26))

    older = client.get(route, params={"limit": 20, "offset": 20})
    assert older.status_code == 200
    older_payload = older.json()
    assert older_payload["has_more"] is False
    assert [item["sequence"] for item in older_payload["items"]] == list(range(1, 6))


def test_conversation_history_is_not_accessible_across_organizations(
    client, db_session, organization_context
):
    conversation = _conversation_with_messages(
        db_session,
        organization_context["organization"].id,
        organization_context["owner"].id,
        count=2,
    )
    other_organization_id = uuid4()
    route = (
        f"/api/v1/organizations/{other_organization_id}"
        f"/conversations/{conversation.id}/messages"
    )

    response = client.get(route)

    assert response.status_code == 404


def test_member_can_rename_conversation(client, db_session, organization_context):
    conversation = _conversation_with_messages(
        db_session,
        organization_context["organization"].id,
        organization_context["owner"].id,
        count=2,
    )
    response = client.patch(
        f"/api/v1/organizations/{organization_context['organization'].id}/conversations/{conversation.id}",
        json={"title": "Updated policy discussion"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Updated policy discussion"
    db_session.refresh(conversation)
    assert conversation.title_is_user_edited is True


def test_deleting_conversation_also_deletes_its_checkpoints(
    client, db_session, organization_context, monkeypatch
):
    conversation = _conversation_with_messages(
        db_session,
        organization_context["organization"].id,
        organization_context["owner"].id,
        count=2,
    )
    fake_checkpointer = FakeCheckpointer()
    monkeypatch.setattr(
        "app.api.v1.endpoints.conversations.get_checkpointer",
        lambda: fake_checkpointer,
    )

    response = client.delete(
        f"/api/v1/organizations/{organization_context['organization'].id}/conversations/{conversation.id}"
    )

    assert response.status_code == 204
    assert fake_checkpointer.deleted_threads == [str(conversation.id)]
    assert db_session.get(Conversation, conversation.id) is None
    assert (
        db_session.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation.id)
        .count()
        == 0
    )


def test_paginated_history_restores_saved_feedback_status(
    client, db_session, organization_context
):
    from uuid import uuid4

    from app.models import GenerationFeedback

    generation_id = uuid4()
    conversation = Conversation(
        organization_id=organization_context["organization"].id,
        user_id=organization_context["owner"].id,
        title="Feedback restoration",
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            sequence=1,
            role="assistant",
            content="The policy provides 20 days.",
            message_metadata={"generation_id": str(generation_id)},
        )
    )
    db_session.add(
        GenerationFeedback(
            id=generation_id,
            organization_id=organization_context["organization"].id,
            user_id=organization_context["owner"].id,
            query="How much annual leave?",
            generated_queries=[],
            generated_query_count=0,
            retrieval_trace={},
            retrieved_documents=[],
            answer_markdown="The policy provides 20 days.",
            answer_status="answered",
            feedback_status="relevant",
        )
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/organizations/{organization_context['organization'].id}/conversations/{conversation.id}/messages"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["metadata"]["feedback_status"] == "relevant"
