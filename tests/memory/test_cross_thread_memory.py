from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.memory.cross_thread_memory import (
    CrossThreadMemoryService,
    _namespace,
    _parse_memories,
    retrieve_cross_thread_memories,
)


class FakeStore:
    def __init__(self):
        self.items = {}
        self.put_calls = []

    async def aget(self, namespace, key):
        value = self.items.get((namespace, key))
        return SimpleNamespace(value=value) if value is not None else None

    async def aput(self, namespace, key, value, *, index=None):
        self.items[(namespace, key)] = value
        self.put_calls.append((namespace, key, value, index))

    async def asearch(self, namespace, *, query=None, limit=10):
        return [
            SimpleNamespace(value=value)
            for (stored_namespace, key), value in self.items.items()
            if stored_namespace == namespace
            and key.startswith("fact:")
            and (query is None or query.lower() in value.get("text", "").lower())
        ][:limit]

    async def adelete(self, namespace, key):
        self.items.pop((namespace, key), None)


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
        return SimpleNamespace(content=self.content)


class FakeLLMClient:
    def __init__(self, content):
        self.llm = FakeLLM(content)

    def get_llm(self, **kwargs):
        assert kwargs == {"temperature": 0, "max_output_tokens": 512}
        return self.llm


def test_namespace_is_organization_and_user_scoped():
    organization_id = uuid4()
    user_id = uuid4()
    assert _namespace(organization_id, user_id) == (
        str(organization_id),
        str(user_id),
    )
    assert _namespace(organization_id, uuid4()) != _namespace(
        organization_id, user_id
    )


def test_parse_memories_accepts_only_supported_categories_and_valid_facts():
    parsed = _parse_memories(
        """```json
        {"memories":[
          {"subject":"response_style","category":"preference","text":"Prefer concise answers."},
          {"subject":"bad","category":"medical","text":"Sensitive detail"},
          {"subject":"","category":"profile","text":"Missing subject"}
        ]}
        ```"""
    )
    assert parsed == [
        {
            "subject": "response_style",
            "category": "preference",
            "text": "Prefer concise answers.",
        }
    ]


@pytest.mark.asyncio
async def test_remember_user_message_upserts_scoped_facts_and_is_idempotent():
    organization_id, user_id = uuid4(), uuid4()
    conversation_id, request_id = uuid4(), uuid4()
    store = FakeStore()
    llm_client = FakeLLMClient(
        '{"memories":[{"subject":"response_style","category":"preference",'
        '"text":"Prefers concise technical answers."}]}'
    )
    service = CrossThreadMemoryService(store, llm_client=llm_client)

    count = await service.remember_user_message(
        organization_id=organization_id,
        user_id=user_id,
        conversation_id=conversation_id,
        request_id=request_id,
        user_message="Please keep technical answers concise.",
    )
    assert count == 1
    namespace = (str(organization_id), str(user_id))
    fact = store.items[(namespace, "fact:response_style")]
    assert fact["text"] == "Prefers concise technical answers."
    assert fact["source_conversation_id"] == str(conversation_id)
    assert store.items[(namespace, f"processed-turn:{request_id}")]["processed"] is True

    repeated = await service.remember_user_message(
        organization_id=organization_id,
        user_id=user_id,
        conversation_id=conversation_id,
        request_id=request_id,
        user_message="Please keep technical answers concise.",
    )
    assert repeated == 0
    assert llm_client.llm.calls == 1


@pytest.mark.asyncio
async def test_retrieval_uses_only_the_authenticated_namespace():
    organization_id, user_id, another_user_id = uuid4(), uuid4(), uuid4()
    store = FakeStore()
    namespace = (str(organization_id), str(user_id))
    other_namespace = (str(organization_id), str(another_user_id))
    store.items[(namespace, "fact:project")] = {
        "text": "SaviraCortex uses PostgreSQL for conversation state.",
        "category": "project",
        "subject": "project",
    }
    store.items[(other_namespace, "fact:project")] = {
        "text": "Private information for another user.",
        "category": "project",
        "subject": "project",
    }

    service = CrossThreadMemoryService(store)
    results = await service.retrieve(
        organization_id=organization_id,
        user_id=user_id,
        query="PostgreSQL",
    )
    assert results == [
        {
            "text": "SaviraCortex uses PostgreSQL for conversation state.",
            "category": "project",
            "subject": "project",
        }
    ]


@pytest.mark.asyncio
async def test_langgraph_memory_node_uses_state_namespace():
    organization_id, user_id = uuid4(), uuid4()
    store = FakeStore()
    namespace = (str(organization_id), str(user_id))
    store.items[(namespace, "fact:preference")] = {
        "text": "Prefers direct answers.",
        "category": "preference",
        "subject": "preference",
    }

    result = await retrieve_cross_thread_memories(
        {
            "organization_id": organization_id,
            "user_id": user_id,
            "query": "direct answers",
        },
        store=store,
    )
    assert result["long_term_memories"][0]["text"] == "Prefers direct answers."
