import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from app.agents.Retrieval_expansion_legacy import (
    InvalidExpansionInputError,
    RetrievalExpansionAgent,
    RetrievalExpansionConfig,
    RetrievalExpansionOutput,
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
        }
    ]


def make_agent():
    return RetrievalExpansionAgent(
        model=RunnableLambda(lambda _: "{}"),
    )


def test_expand_returns_structured_retrieval_guidance(sample_candidates):
    agent = make_agent()
    expected = RetrievalExpansionOutput(
        rewritten_query=(
            "Company annual leave approval workflow, eligibility, "
            "submission requirements and approval authority"
        ),
        hypothetical_answer=(
            "The leave policy describes the request submission process, "
            "eligibility conditions, approval responsibilities and timelines."
        ),
    )
    agent.chain = RunnableLambda(lambda _: expected)

    result = agent.expand(
        original_query="How many leave days and how is leave approved?",
        current_retrieval_query="How many leave days and how is leave approved?",
        missing_information=["The annual leave approval process."],
        retrieved_documents=sample_candidates,
    )

    assert result == expected


def test_prompt_contains_inputs_and_excludes_private_metadata(sample_candidates):
    agent = make_agent()
    history = [HumanMessage(content="We are discussing the annual leave policy.")]
    evidence = agent._prepare_evidence(sample_candidates)
    payload = agent._build_payload(
        original_query="How many leave days and who approves them?",
        current_retrieval_query="Annual leave approval procedure",
        missing_information=["Approval authority and request steps."],
        retrieved_evidence=evidence,
        conversation_history=history,
    )
    rendered = agent.prompt.invoke(payload).to_string()

    assert "How many leave days and who approves them?" in rendered
    assert "Annual leave approval procedure" in rendered
    assert "Approval authority and request steps." in rendered
    assert "We are discussing the annual leave policy." in rendered
    assert "20 days of annual leave" in rendered
    assert "Leave Policy.pdf" in rendered
    assert "private-document-id" not in rendered
    assert "private-version-id" not in rendered
    assert "private-organization-id" not in rendered
    assert "private-chunk-1" not in rendered
    assert "global_rrf_score" not in rendered
    assert "reranker_score" not in rendered
    assert "never verified evidence" in rendered


def test_previous_retrieval_query_defaults_to_original_query():
    payload = RetrievalExpansionAgent._build_payload(
        original_query="What is the leave policy?",
        current_retrieval_query="What is the leave policy?",
        missing_information=["Leave approval process."],
        retrieved_evidence=[],
        conversation_history=None,
    )

    assert payload["current_retrieval_query_json"] == '"What is the leave policy?"'
    assert payload["conversation_history"] == []


def test_missing_documents_are_allowed_for_hypothetical_expansion():
    agent = make_agent()
    expected = RetrievalExpansionOutput(
        rewritten_query="Company travel reimbursement eligibility criteria",
        hypothetical_answer=(
            "The reimbursement policy explains eligible expenses, "
            "submission requirements and approval responsibilities."
        ),
    )
    agent.chain = RunnableLambda(lambda _: expected)

    result = agent.expand(
        original_query="What travel costs can I claim?",
        missing_information=["Eligible travel expenses and claim conditions."],
    )

    assert result == expected


@pytest.mark.asyncio
async def test_async_expansion(sample_candidates):
    agent = make_agent()
    expected = RetrievalExpansionOutput(
        rewritten_query="Annual leave request approval authority",
        hypothetical_answer="The policy describes the approval authority for leave requests.",
    )
    agent.chain = RunnableLambda(lambda _: expected)

    result = await agent.aexpand(
        original_query="Who approves annual leave?",
        missing_information=["The role responsible for approving annual leave."],
        retrieved_documents=sample_candidates,
    )

    assert result == expected


@pytest.mark.parametrize(
    ("query", "missing"),
    [
        ("", ["Missing requirement."]),
        ("Valid query", []),
        ("Valid query", ["  "]),
        ("Valid query", "Missing requirement."),
    ],
)
def test_invalid_expansion_inputs_are_rejected(query, missing):
    with pytest.raises(InvalidExpansionInputError):
        make_agent().expand(
            original_query=query,
            missing_information=missing,
        )


def test_schema_rejects_extra_or_empty_fields():
    with pytest.raises(ValidationError):
        RetrievalExpansionOutput(
            rewritten_query="A valid retrieval query",
            hypothetical_answer="A valid hypothetical passage",
            extra_field="not allowed",
        )

    with pytest.raises(ValidationError):
        RetrievalExpansionOutput(
            rewritten_query="  ",
            hypothetical_answer="A valid hypothetical passage",
        )


def test_config_rejects_invalid_values():
    with pytest.raises(ValueError):
        RetrievalExpansionConfig(temperature=2.1)

    with pytest.raises(ValueError):
        RetrievalExpansionConfig(max_output_tokens=0)
