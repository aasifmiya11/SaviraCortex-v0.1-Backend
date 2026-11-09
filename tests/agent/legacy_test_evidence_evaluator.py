import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from app.agents.Evidence_evaluator_legacy import (
    EmptyQueryError,
    EvidenceEvaluation,
    EvidenceEvaluatorAgent,
    EvidenceEvaluatorConfig,
)


@pytest.fixture
def sample_candidates():
    return [
        {
            "chunk_id": "private-chunk-1",
            "page_content": "Employees receive 20 days of annual leave.",
            "metadata": {
                "document_id": "private-document-id",
                "document_version_id": "private-version-id",
                "source_filename": "Leave Policy.pdf",
                "page": 4,
                "section_heading": "Annual Leave",
                "organization_id": "private-organization-id",
            },
            "global_rrf_score": 0.04,
            "reranker_score": 0.91,
        },
        {
            "chunk_id": "private-chunk-2",
            "page_content": "Unused annual leave can be carried forward up to 5 days.",
            "metadata": {"source": "Leave Policy.pdf", "page": 5},
        },
    ]


def make_agent():
    return EvidenceEvaluatorAgent(
        model=RunnableLambda(lambda _: "{}"),
    )


def test_evaluate_returns_structured_sufficiency_judgment(sample_candidates):
    agent = make_agent()
    expected = EvidenceEvaluation(
        is_sufficient=False,
        missing_information=["The applicable leave approval process."],
    )
    agent.chain = RunnableLambda(lambda _: expected)

    result = agent.evaluate(
        current_query="How many leave days are provided and how is leave approved?",
        retrieved_documents=sample_candidates,
    )

    assert result == expected
    assert result.is_sufficient is False
    assert result.missing_information == [
        "The applicable leave approval process."
    ]


def test_prompt_contains_query_history_and_safe_evidence(sample_candidates):
    agent = make_agent()
    history = [
        HumanMessage(content="What does our leave policy say?"),
        AIMessage(content="It covers annual leave."),
    ]
    evidence = agent._prepare_evidence(sample_candidates)
    rendered = agent.prompt.invoke(
        agent._build_payload(
            "How many days can be carried forward?",
            evidence,
            history,
        )
    ).to_string()

    assert "How many days can be carried forward?" in rendered
    assert "What does our leave policy say?" in rendered
    assert "20 days of annual leave" in rendered
    assert "Leave Policy.pdf" in rendered
    assert "private-document-id" not in rendered
    assert "private-version-id" not in rendered
    assert "private-organization-id" not in rendered
    assert "private-chunk-1" not in rendered
    assert "global_rrf_score" not in rendered
    assert "reranker_score" not in rendered


def test_history_is_passed_without_modification(sample_candidates):
    agent = make_agent()
    history = [HumanMessage(content="What is the leave policy?")]
    original = history.copy()
    captured = {}

    def fake_chain(payload):
        captured.update(payload)
        return EvidenceEvaluation(
            is_sufficient=True,
            missing_information=[],
        )

    agent.chain = RunnableLambda(fake_chain)
    agent.evaluate("How many days?", sample_candidates, history)

    assert captured["conversation_history"] == original
    assert history == original


def test_no_usable_evidence_returns_insufficient_without_llm_call():
    agent = make_agent()
    called = False

    def unexpected_call(_):
        nonlocal called
        called = True
        raise AssertionError("LLM must not run without usable evidence.")

    agent.chain = RunnableLambda(unexpected_call)
    result = agent.evaluate("What is the leave policy?", [])

    assert result.is_sufficient is False
    assert result.missing_information
    assert called is False


def test_empty_query_is_rejected():
    with pytest.raises(EmptyQueryError):
        make_agent().evaluate("  ", [])


@pytest.mark.asyncio
async def test_async_evaluation(sample_candidates):
    agent = make_agent()
    expected = EvidenceEvaluation(
        is_sufficient=True,
        missing_information=[],
    )
    agent.chain = RunnableLambda(lambda _: expected)

    result = await agent.aevaluate(
        "How many annual leave days are provided?",
        sample_candidates,
    )

    assert result == expected


def test_schema_rejects_inconsistent_sufficiency_judgment():
    with pytest.raises(ValidationError):
        EvidenceEvaluation(
            is_sufficient=True,
            missing_information=["A missing requirement."],
        )

    with pytest.raises(ValidationError):
        EvidenceEvaluation(
            is_sufficient=False,
            missing_information=[],
        )


def test_config_rejects_invalid_values():
    with pytest.raises(ValueError):
        EvidenceEvaluatorConfig(temperature=2.1)

    with pytest.raises(ValueError):
        EvidenceEvaluatorConfig(max_output_tokens=0)
