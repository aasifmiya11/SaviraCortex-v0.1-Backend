import pytest

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from app.agents.Generation import (
    GenerationAgent,
    GenerationConfig,
    GenerationOutput,
    GenerationStatus,
    GenerationStreamEventType,
)
from app.agents.Generation.schemas import AnswerSegment


@pytest.fixture
def sample_candidates():
    return [
        {
            "chunk_id": "internal-chunk-1",
            "page_content": (
                "Employees are entitled to 20 days of annual leave "
                "per calendar year."
            ),
            "metadata": {
                "document_id": "internal-document-id",
                "document_version_id": "internal-version-id",
                "source": "Employee Leave Policy.pdf",
                "page": 4,
                "chunk_index": 3,
                "organization_id": "internal-organization-id",
            },
            "global_rank": 1,
            "global_rrf_score": 0.04,
            "reranker_score": 0.91,
            "provenance": [],
        },
        {
            "chunk_id": "internal-chunk-2",
            "page_content": (
                "Unused annual leave can be carried forward up to 5 days."
            ),
            "metadata": {
                "source_filename": "Employee Leave Policy.pdf",
                "page": 5,
                "section_heading": "Leave Carry Forward",
            },
            "global_rank": 2,
            "global_rrf_score": 0.03,
            "reranker_score": 0.82,
            "provenance": [],
        },
    ]


def make_agent():
    return GenerationAgent(
        model=RunnableLambda(lambda _: "A supported answer[1].")
    )


def test_generate_returns_plain_markdown_with_validated_numeric_citations(sample_candidates):
    agent = make_agent()
    agent.chain = RunnableLambda(
        lambda _: "## Annual leave\n\nEmployees receive 20 days per year[1]."
    )

    result = agent.generate(
        current_query="How many annual leave days do employees receive?",
        retrieved_documents=sample_candidates,
    )

    assert isinstance(result, GenerationOutput)
    assert result.status == GenerationStatus.ANSWERED
    assert result.segments[0].text.startswith("## Annual leave")
    assert result.segments[0].citations == ["E1"]


def test_prompt_uses_ranked_evidence_and_requests_markdown_citations(sample_candidates):
    agent = make_agent()
    evidence = agent._prepare_evidence(sample_candidates)

    rendered = agent.prompt.invoke(
        {
            "current_query_json": '"How many leave days?"',
            "conversation_history": [],
            "retrieved_evidence_json": __import__("json").dumps(evidence),
        }
    ).to_string()

    assert '"evidence_id": "E1"' in rendered
    assert '"evidence_id": "E2"' in rendered
    assert "Employee Leave Policy.pdf" in rendered
    assert '"page": 4' in rendered
    assert "Leave Carry Forward" in rendered
    assert "20 days of annual leave" in rendered
    assert "Markdown" in rendered
    assert "Cite evidence item E1 with the inline Markdown marker [1]" in rendered
    assert "Return only the Markdown answer" in rendered
    assert "format_instructions" not in rendered

    # Backend-only identifiers and retrieval scores must not enter the prompt.
    assert "internal-document-id" not in rendered
    assert "internal-version-id" not in rendered
    assert "internal-organization-id" not in rendered
    assert "global_rrf_score" not in rendered
    assert "reranker_score" not in rendered
    assert "internal-chunk-1" not in rendered


def test_history_is_passed_without_modification(sample_candidates):
    agent = make_agent()
    history = [
        HumanMessage(content="What is the leave policy?"),
        AIMessage(content="The documents describe annual leave."),
    ]
    original = history.copy()
    captured = {}

    def fake_chain(payload):
        captured.update(payload)
        return "The policy grants 20 days[1]."

    agent.chain = RunnableLambda(fake_chain)
    agent.generate(
        current_query="How many days?",
        retrieved_documents=sample_candidates,
        conversation_history=history,
    )

    assert captured["conversation_history"] == original
    assert history == original


def test_empty_retrieval_returns_insufficient_evidence_without_llm_call():
    agent = make_agent()
    called = False

    def unexpected_call(_):
        nonlocal called
        called = True
        raise AssertionError("LLM should not be called without evidence.")

    agent.chain = RunnableLambda(unexpected_call)
    result = agent.generate(
        current_query="What is the annual leave policy?",
        retrieved_documents=[],
    )

    assert result.status == GenerationStatus.INSUFFICIENT_EVIDENCE
    assert result.segments[0].citations == []
    assert "don't have enough information" in result.segments[0].text
    assert called is False


@pytest.mark.asyncio
async def test_async_generation_returns_markdown_and_partial_status(sample_candidates):
    agent = make_agent()
    agent.chain = RunnableLambda(lambda _: "The evidence confirms the entitlement[1].")

    result = await agent.agenerate(
        current_query="Explain annual leave.",
        retrieved_documents=sample_candidates,
        status=GenerationStatus.PARTIAL,
    )

    assert result.status == GenerationStatus.PARTIAL
    assert result.segments[0].text == "The evidence confirms the entitlement[1]."
    assert result.segments[0].citations == ["E1"]


@pytest.mark.asyncio
async def test_streaming_emits_markdown_deltas_then_validated_output(sample_candidates):
    agent = make_agent()

    class FakeStreamingChain:
        async def astream(self, _payload, config=None):
            yield "## Annual leave\n\nEmployees receive "
            yield "20 days per year[1]."

    agent.streaming_chain = FakeStreamingChain()
    events = [
        event
        async for event in agent.astream_generate(
            current_query="Summarize annual leave.",
            retrieved_documents=sample_candidates,
        )
    ]

    content_events = [
        event for event in events
        if event.event_type == GenerationStreamEventType.CONTENT_DELTA
    ]
    completed_events = [
        event for event in events
        if event.event_type == GenerationStreamEventType.COMPLETED
    ]

    assert "".join(event.delta for event in content_events) == (
        "## Annual leave\n\nEmployees receive 20 days per year[1]."
    )
    assert len(completed_events) == 1
    assert completed_events[0].output.segments[0].citations == ["E1"]
    assert events[-1].event_type == GenerationStreamEventType.COMPLETED


@pytest.mark.asyncio
async def test_streaming_rejects_unknown_numeric_citation_after_emitting_markdown(
    sample_candidates,
):
    agent = make_agent()

    class FakeStreamingChain:
        async def astream(self, _payload, config=None):
            yield "This answer cites an unknown source[99]."

    agent.streaming_chain = FakeStreamingChain()
    events = []

    from app.agents.Generation import CitationValidationError

    with pytest.raises(CitationValidationError) as exc_info:
        async for event in agent.astream_generate(
            current_query="Question?",
            retrieved_documents=sample_candidates,
        ):
            events.append(event)

    assert any(
        event.event_type == GenerationStreamEventType.CONTENT_DELTA
        for event in events
    )
    assert exc_info.value.invalid_citations == ("E99",)
    assert not any(
        event.event_type == GenerationStreamEventType.COMPLETED
        for event in events
    )


@pytest.mark.asyncio
async def test_streaming_without_evidence_emits_only_completed_event():
    agent = make_agent()
    events = [
        event
        async for event in agent.astream_generate(
            current_query="Question?",
            retrieved_documents=[],
        )
    ]

    assert len(events) == 1
    assert events[0].event_type == GenerationStreamEventType.COMPLETED
    assert events[0].output.status == GenerationStatus.INSUFFICIENT_EVIDENCE


def test_config_rejects_invalid_values():
    with pytest.raises(ValueError):
        GenerationConfig(temperature=2.1)
    with pytest.raises(ValueError):
        GenerationConfig(max_output_tokens=0)


def test_output_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        GenerationOutput.model_validate(
            {
                "status": "answered",
                "segments": [{
                    "text": "Answer",
                    "citations": [],
                    "url": "https://example.com",
                }],
            }
        )


def test_prompt_receives_injection_security_label_without_internal_metadata_leakage(sample_candidates):
    agent = make_agent()
    flagged = [
        {
            **sample_candidates[0],
            "metadata": {
                **sample_candidates[0]["metadata"],
                "prompt_injection_flagged": True,
                "security_review_decision": "ingest_anyway",
                "security_review_confidence": 0.97,
            },
        }
    ]

    evidence = agent._prepare_evidence(flagged)

    assert evidence[0]["security_label"] == "PROMPT_INJECTION_FLAGGED"
    assert evidence[0]["security_decision"] == "ingest_anyway"
    assert "security_review_confidence" not in evidence[0]
    assert "internal-organization-id" not in str(evidence)
