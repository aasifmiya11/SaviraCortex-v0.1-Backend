from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from app.agents.Generation.schemas import AnswerSegment, GenerationOutput, GenerationStatus
from app.schemas.v1.generation import GenerationResponse
from app.services.generation.persistent_generation_service import (
    PersistentGenerationService,
)
from app.validation.schemas import CitationReference, GenerationValidationResult


def make_valid_result(query: str):
    output = GenerationOutput(
        status=GenerationStatus.ANSWERED,
        segments=[AnswerSegment(text="The policy provides 20 days[1].", citations=["E1"])],
    )
    validation = GenerationValidationResult(
        is_valid=True,
        output=output,
        citations=[
            CitationReference(
                evidence_id="E1",
                document_id=str(uuid4()),
                document_version_id=str(uuid4()),
                document_title="Leave Policy",
                page=4,
            )
        ],
    )
    return {
        "query": query,
        "is_valid": True,
        "generation_output": output,
        "validation_result": validation,
        "retrieved_documents": [{"page_content": "20 days", "metadata": {}}],
        "retrieval_attempt": 1,
        "missing_information": [],
    }


class FakePersistentGraph:
    def __init__(self, result):
        self.result = result
        self.input_state = None
        self.config = None
        self.updated_state = None

    async def ainvoke(self, state, config=None):
        self.input_state = state
        self.config = config
        return self.result

    async def aupdate_state(self, config, values):
        self.config = config
        self.updated_state = values


class FakeConversationRepository:
    def __init__(self, conversation_id, existing_response=None):
        self.conversation = SimpleNamespace(id=conversation_id)
        self.existing_response = existing_response
        self.assistant_message = None
        self.user_messages = []

    def find_by_initial_request(self, **kwargs):
        return None

    def create_with_user_message(self, **kwargs):
        self.user_messages.append(kwargs)
        return self.conversation

    def append_user_message(self, **kwargs):
        self.user_messages.append(kwargs)

    def get_assistant_response(self, conversation_id, request_id):
        return self.existing_response

    def append_assistant_message(self, **kwargs):
        self.assistant_message = kwargs


@pytest.mark.asyncio
async def test_persistent_generation_uses_backend_conversation_as_thread_id():
    conversation_id = uuid4()
    request_id = uuid4()
    graph = FakePersistentGraph(make_valid_result("Explain the leave policy."))
    service = PersistentGenerationService(
        object(),
        checkpointer=object(),
        graph_factory=lambda _session: graph,
    )
    repository = FakeConversationRepository(conversation_id)
    service.conversations = repository
    generation_id = uuid4()
    service._persist_generation_record = lambda **_kwargs: generation_id

    response = await service.generate(
        query="Explain the leave policy.",
        organization_id=uuid4(),
        user_id=uuid4(),
        request_id=request_id,
    )

    assert response.conversation_id == conversation_id
    assert response.request_id == request_id
    assert response.generation_id == generation_id
    assert graph.config == {"configurable": {"thread_id": str(conversation_id)}}
    assert "conversation_history" not in graph.input_state
    assert len(graph.input_state["messages"]) == 1
    assert isinstance(graph.input_state["messages"][0], HumanMessage)
    assert graph.input_state["messages"][0].id == str(request_id)
    assert graph.updated_state["messages"][0].id == f"assistant:{request_id}"
    assert isinstance(graph.updated_state["messages"][0], AIMessage)
    assert repository.assistant_message["request_id"] == request_id


@pytest.mark.asyncio
async def test_persistent_generation_returns_idempotent_saved_response_without_graph():
    conversation_id = uuid4()
    request_id = uuid4()
    saved_response = GenerationResponse(
        generation_id=uuid4(),
        conversation_id=conversation_id,
        request_id=request_id,
        query="Explain the leave policy.",
        answer="Saved response.",
        status=GenerationStatus.ANSWERED,
        citations=[],
        warnings=[],
        missing_information=[],
        retrieval_attempts=1,
        evidence_count=1,
    ).model_dump(mode="json")

    service = PersistentGenerationService(
        object(),
        checkpointer=object(),
        graph_factory=lambda _session: (_ for _ in ()).throw(AssertionError("graph should not run")),
    )
    repository = FakeConversationRepository(conversation_id, existing_response=saved_response)
    service.conversations = repository

    response = await service.generate(
        query="Explain the leave policy.",
        organization_id=uuid4(),
        user_id=uuid4(),
        request_id=request_id,
    )

    assert response.answer == "Saved response."
    assert response.conversation_id == conversation_id


@pytest.mark.asyncio
async def test_conversation_title_generation_is_background_safe_and_never_overwrites_manual_title(
    monkeypatch,
):
    from types import SimpleNamespace

    from app.services.generation.persistent_generation_service import (
        generate_conversation_title,
    )

    class FakeLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content="  Leave Policy Overview  ")

    class FakeLLMClient:
        def get_llm(self, **kwargs):
            assert kwargs["temperature"] == 0
            return FakeLLM()

    class FakeSession:
        def __init__(self):
            self.statement = None
            self.committed = False
            self.closed = False

        def execute(self, statement):
            self.statement = statement

        def commit(self):
            self.committed = True

        def close(self):
            self.closed = True

    fake_session = FakeSession()
    monkeypatch.setattr(
        "app.llm.generator_client.generator_llm_client",
        FakeLLMClient(),
    )
    monkeypatch.setattr(
        "app.core.database.SessionLocal",
        lambda: fake_session,
    )

    await generate_conversation_title(
        conversation_id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        first_message="Explain our annual leave policy in simple terms.",
    )

    compiled = fake_session.statement.compile()
    assert "Leave Policy Overview" in compiled.params.values()
    assert "title_is_user_edited" in str(fake_session.statement)
    assert "title_generated" in str(fake_session.statement)
    assert fake_session.committed is True
    assert fake_session.closed is True
