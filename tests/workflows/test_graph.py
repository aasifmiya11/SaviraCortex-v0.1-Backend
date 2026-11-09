from uuid import uuid4

import pytest

from app.agents.Generation.schemas import (
    AnswerSegment,
    GenerationOutput,
    GenerationStatus,
    GenerationStreamEvent,
    GenerationStreamEventType,
)
from app.services.retrieval.retrieval_service import RetrievalOrchestrationError
from app.validation.schemas import GenerationValidationResult
from app.workflows.rag.graph import create_rag_graph


class FakeRetriever:
    def __init__(self, documents=None):
        self.calls = []
        self.documents = documents or [{
            "chunk_id": "doc-version:0",
            "page_content": "The company provides 20 days of annual leave.",
            "metadata": {"document_id": "doc"},
        }]

    async def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "selected_candidates": self.documents,
            "selected_count": len(self.documents),
            "eligible_count": len(self.documents),
            "fused_count": len(self.documents),
            "reranked_count": len(self.documents),
            "branch_count": 1,
            "retrieval_attempt": 1,
            "expansion": {"rounds_performed": 0, "stop_reason": "disabled_single_pass"},
        }


class FakeGenerationAgent:
    def __init__(self):
        self.calls = []

    async def agenerate(self, **kwargs):
        self.calls.append(kwargs)
        return GenerationOutput(
            status=GenerationStatus.ANSWERED,
            segments=[AnswerSegment(
                text="The annual leave entitlement is 20 days.",
                citations=["E1"],
            )],
        )


class FakeValidator:
    def validate_generation_output(self, output, retrieved_documents):
        return GenerationValidationResult(
            is_valid=True,
            output=output,
            citations=[],
        )


def build_graph(retriever=None, generation=None):
    return create_rag_graph(
        retriever=retriever or FakeRetriever(),
        generation_agent=generation or FakeGenerationAgent(),
        validator=FakeValidator(),
    )


@pytest.mark.asyncio
async def test_graph_runs_retrieval_directly_into_generation_once():
    retriever = FakeRetriever()
    generation = FakeGenerationAgent()
    graph = build_graph(retriever, generation)

    result = await graph.ainvoke({
        "query": "How many annual leave days are provided?",
        "organization_id": uuid4(),
        "user_id": uuid4(),
    })

    assert result["is_valid"] is True
    assert result["retrieval_attempt"] == 1
    assert len(retriever.calls) == 1
    assert len(generation.calls) == 1
    assert generation.calls[0]["retrieved_documents"] == retriever.documents
    assert generation.calls[0]["current_query"] == "How many annual leave days are provided?"
    assert result["generation_output"].status == GenerationStatus.ANSWERED
    assert result["validation_result"].is_valid is True


@pytest.mark.asyncio
async def test_graph_ends_after_invalid_input_without_retrieval():
    retriever = FakeRetriever()
    generation = FakeGenerationAgent()
    graph = build_graph(retriever, generation)

    result = await graph.ainvoke({
        "query": "!!!",
        "organization_id": uuid4(),
        "user_id": uuid4(),
    })

    assert result["is_valid"] is False
    assert result["validation_error"]
    assert retriever.calls == []
    assert generation.calls == []
    assert "generation_output" not in result


@pytest.mark.asyncio
async def test_single_pass_generates_even_when_adaptive_k_returns_few_documents():
    documents = [{"chunk_id": "doc:0", "page_content": "One selected chunk.", "metadata": {}}]
    retriever = FakeRetriever(documents)
    generation = FakeGenerationAgent()
    graph = build_graph(retriever, generation)

    result = await graph.ainvoke({
        "query": "Summarize the policy.",
        "organization_id": uuid4(),
        "user_id": uuid4(),
    })

    assert len(retriever.calls) == 1
    assert len(generation.calls) == 1
    assert generation.calls[0]["retrieved_documents"] == documents
    assert result["generation_output"].status == GenerationStatus.ANSWERED


class CandidateGenerationFailureRetriever:
    async def retrieve(self, **kwargs):
        raise RetrievalOrchestrationError("candidate generation failed")


@pytest.mark.asyncio
async def test_graph_surfaces_retrieval_failure_without_entering_generation():
    generation = FakeGenerationAgent()
    graph = build_graph(CandidateGenerationFailureRetriever(), generation)

    with pytest.raises(RetrievalOrchestrationError):
        await graph.ainvoke({
            "query": "What does the company policy say?",
            "organization_id": uuid4(),
            "user_id": uuid4(),
        })
    assert generation.calls == []


class StreamingFakeGenerationAgent:
    async def astream_generate(self, **kwargs):
        output = GenerationOutput(
            status=GenerationStatus.ANSWERED,
            segments=[AnswerSegment(
                text="The annual leave entitlement is 20 days.",
                citations=["E1"],
            )],
        )
        yield GenerationStreamEvent(
            event_type=GenerationStreamEventType.CONTENT_DELTA,
            segment_index=0,
            delta="The annual leave entitlement is 20 days.",
        )
        yield GenerationStreamEvent(
            event_type=GenerationStreamEventType.COMPLETED,
            output=output,
        )


@pytest.mark.asyncio
async def test_graph_streams_generation_and_keeps_static_citation_validation():
    events = []
    graph = create_rag_graph(
        retriever=FakeRetriever(),
        generation_agent=StreamingFakeGenerationAgent(),
        validator=FakeValidator(),
        generation_event_callback=events.append,
    )

    result = await graph.ainvoke({
        "query": "How many annual leave days are provided?",
        "organization_id": uuid4(),
        "user_id": uuid4(),
    })

    assert events == [{
        "type": "delta",
        "segment_index": 0,
        "delta": "The annual leave entitlement is 20 days.",
    }]
    assert result["validation_result"].is_valid is True
