from uuid import uuid4

import pytest

from app.models import ConversationMessage
from app.repositories.conversation_repository import ConversationRepository


def test_conversation_repository_allocates_stable_message_sequences(
    db_session, organization_context
):
    repository = ConversationRepository(db_session)
    request_id = uuid4()
    conversation = repository.create_with_user_message(
        organization_id=organization_context["organization"].id,
        user_id=organization_context["owner"].id,
        request_id=request_id,
        content="  Explain our leave policy.  ",
    )

    repository.append_user_message(
        conversation=conversation,
        request_id=uuid4(),
        content="How many days are available?",
    )
    repository.append_assistant_message(
        conversation=conversation,
        request_id=uuid4(),
        content="The policy provides 20 days.",
        metadata={"status": "answered"},
    )

    messages, total = repository.list_messages(
        conversation_id=conversation.id,
        limit=20,
        offset=0,
    )

    assert total == 3
    assert [message.sequence for message in messages] == [1, 2, 3]
    assert [message.role for message in messages] == ["user", "user", "assistant"]
    assert messages[0].content == "  Explain our leave policy.  "


def test_initial_request_id_makes_conversation_creation_idempotent(
    db_session, organization_context
):
    repository = ConversationRepository(db_session)
    request_id = uuid4()
    kwargs = {
        "organization_id": organization_context["organization"].id,
        "user_id": organization_context["owner"].id,
        "request_id": request_id,
        "content": "Summarize our policy.",
    }

    first = repository.create_with_user_message(**kwargs)
    retry = repository.create_with_user_message(**kwargs)

    assert first.id == retry.id
    assert repository.find_by_initial_request(
        organization_id=kwargs["organization_id"],
        user_id=kwargs["user_id"],
        request_id=request_id,
    ).id == first.id
    assert (
        db_session.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == first.id,
            ConversationMessage.request_id == request_id,
            ConversationMessage.role == "user",
        )
        .count()
        == 1
    )


def test_request_id_cannot_be_reused_for_different_message_content(
    db_session, organization_context
):
    repository = ConversationRepository(db_session)
    conversation = repository.create_with_user_message(
        organization_id=organization_context["organization"].id,
        user_id=organization_context["owner"].id,
        request_id=uuid4(),
        content="Initial message",
    )
    request_id = uuid4()
    repository.append_user_message(
        conversation=conversation,
        request_id=request_id,
        content="First version",
    )

    with pytest.raises(ValueError, match="different message"):
        repository.append_user_message(
            conversation=conversation,
            request_id=request_id,
            content="Changed content",
        )
