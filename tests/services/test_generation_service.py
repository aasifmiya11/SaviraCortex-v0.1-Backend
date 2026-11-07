from uuid import uuid4

import pytest

from app.agents.Generation.schemas import (
    AnswerSegment,
    GenerationOutput,
    GenerationStatus,
)
from app.schemas.v1.generation import ConversationTurnRequest
from app.services.generation.generation_service import (
    GenerationService,
    GenerationValidationError,
    InvalidGenerationQueryError,
)
from app.validation.schemas import CitationReference, GenerationValidationResult


class FakeGraph:
    def __init__(self, result):
        self.result = result
        self.input_state = None

    async def ainvoke(self, state):
        self.input_state = state
        return self.result


def valid_result():
    answer = GenerationOutput(
        status=GenerationStatus.ANSWERED,
        segments=[
            AnswerSegment(
                text="The policy provides 20 annual leave days[1].",
                citations=["E1"],
            )
        ],
    )
    validation = GenerationValidationResult(
        is_valid=True,
        output=answer,
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
        "query": "How many annual leave days?",
        "is_valid": True,
        "generation_output": answer,
        "validation_result": validation,
        "retrieved_documents": [
            {"chunk_id": "version:0", "page_content": "20 days", "metadata": {}}
        ],
        "retrieval_attempt": 2,
        "missing_information": [],
    }


@pytest.mark.asyncio
async def test_generation_service_returns_markdown_and_trusted_references():
    graph = FakeGraph(valid_result())
    service = GenerationService(object(), graph_factory=lambda supplied: graph)

    response = await service.generate(
        query="How many annual leave days?",
        organization_id=uuid4(),
        user_id=uuid4(),
        conversation_history=[
            ConversationTurnRequest(role="user", content="We are discussing leave.")
        ],
    )

    assert response.status == GenerationStatus.ANSWERED
    assert response.answer.startswith("The policy provides 20 annual leave days[1].")
    assert "## References" in response.answer
    assert "**[1]** **Leave Policy** - page 4" in response.answer
    assert response.citations[0].evidence_id == "E1"
    assert response.retrieval_attempts == 2
    assert response.evidence_count == 1
    assert graph.input_state["context"][0].content == "We are discussing leave."


@pytest.mark.asyncio
async def test_generation_service_rejects_invalid_query_before_response():
    graph = FakeGraph({
        "is_valid": False,
        "validation_error": "Please enter a meaningful question.",
    })
    service = GenerationService(object(), graph_factory=lambda _session: graph)

    with pytest.raises(InvalidGenerationQueryError):
        await service.generate(
            query="!!!",
            organization_id=uuid4(),
            user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_generation_service_never_returns_an_answer_that_fails_validation():
    result = valid_result()
    result["validation_result"] = GenerationValidationResult(
        is_valid=False,
        output=result["generation_output"],
        errors=["Unknown evidence citation."],
    )
    graph = FakeGraph(result)
    service = GenerationService(object(), graph_factory=lambda _session: graph)

    with pytest.raises(GenerationValidationError):
        await service.generate(
            query="How many annual leave days?",
            organization_id=uuid4(),
            user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_generation_service_stream_emits_markdown_and_validated_references():
    graph = FakeGraph(valid_result())
    events = []
    service = GenerationService(object(), graph_factory=lambda _session: graph)

    response = await service.generate_stream(
        query="How many annual leave days?",
        organization_id=uuid4(),
        user_id=uuid4(),
        on_event=events.append,
    )

    assert response.status == GenerationStatus.ANSWERED
    assert "## References" in response.answer
    assert events[-1]["type"] == "completed"
    assert events[-1]["result"]["citations"][0]["evidence_id"] == "E1"
    assert events[-1]["result"]["answer"] == response.answer
