import pytest

from pydantic import ValidationError

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableLambda

from app.agents.Multi_query_generator import (
    MultiQueryGeneratorAgent,
    MultiQueryGeneratorConfig,
    MultiQueryGeneratorOutput,
    EmptyQueryError,
)


@pytest.fixture
def make_agent(monkeypatch):
    """Create an agent with a mocked parser-compatible LLM."""

    def _make(config=None):
        model = RunnableLambda(
            lambda _: '{"queries": ["Default generated query"]}'
        )

        monkeypatch.setattr(
            "app.agents.Multi_query_generator.agent.llm_client.get_llm",
            lambda: model,
        )

        return MultiQueryGeneratorAgent(config=config)

    return _make


def test_successful_query_generation(make_agent):
    agent = make_agent()

    expected_queries = [
        "RAG retrieval architecture",
        "Techniques for improving RAG retrieval accuracy",
        "Best practices for optimizing retrieval quality",
    ]

    agent.chain = RunnableLambda(
        lambda _: MultiQueryGeneratorOutput(queries=expected_queries)
    )

    result = agent.generate(
        current_query="How can I improve RAG retrieval?",
        conversation_history=[],
    )

    assert len(result) == 3
    assert all(isinstance(message, HumanMessage) for message in result)
    assert [message.content for message in result] == expected_queries


def test_contextual_history_is_preserved(make_agent):
    agent = make_agent()

    history = [
        HumanMessage(content="What is RAG?"),
        AIMessage(content="RAG stands for Retrieval-Augmented Generation."),
        HumanMessage(content="Explain its retrieval architecture."),
        AIMessage(content="It includes query processing and retrieval."),
    ]

    captured = {}

    def mock_generation(payload):
        captured.update(payload)

        return MultiQueryGeneratorOutput(
            queries=["RAG retrieval architecture"]
        )

    agent.chain = RunnableLambda(mock_generation)

    agent.generate(
        current_query="How can we improve its accuracy?",
        conversation_history=history,
    )

    received_history = captured["conversation_history"]

    assert received_history == history
    assert len(received_history) == len(history)

    # Verify original chronological ordering and message objects.
    for received, original in zip(received_history, history):
        assert received is original

    assert captured["current_query"] == "How can we improve its accuracy?"


def test_history_is_not_modified(make_agent):
    agent = make_agent()

    history = [
        HumanMessage(content="What is BM25?"),
        AIMessage(content="BM25 is a lexical ranking algorithm."),
        HumanMessage(content="How does it work?"),
    ]

    original_history = history.copy()

    agent.generate(
        current_query="Explain its scoring mechanism.",
        conversation_history=history,
    )

    assert history == original_history


def test_empty_history_is_supported(make_agent):
    agent = make_agent()

    agent.chain = RunnableLambda(
        lambda _: MultiQueryGeneratorOutput(
            queries=["What is cosine similarity?"]
        )
    )

    result = agent.generate(
        current_query="What is cosine similarity?",
        conversation_history=[],
    )

    assert len(result) == 1
    assert result[0].content == "What is cosine similarity?"


def test_empty_query_is_rejected(make_agent):
    agent = make_agent()

    with pytest.raises(EmptyQueryError):
        agent.generate(
            current_query="",
            conversation_history=[],
        )


def test_whitespace_query_is_rejected(make_agent):
    agent = make_agent()

    with pytest.raises(EmptyQueryError):
        agent.generate(
            current_query="   ",
            conversation_history=[],
        )


def test_custom_configuration(make_agent):
    config = MultiQueryGeneratorConfig(
        max_queries=3,
        temperature=0.1,
        max_output_tokens=1000,
    )

    agent = make_agent(config=config)

    assert agent.config.max_queries == 3
    assert agent.config.temperature == 0.1
    assert agent.config.max_output_tokens == 1000


def test_maximum_query_count_is_enforced(make_agent):
    config = MultiQueryGeneratorConfig(max_queries=3)
    agent = make_agent(config=config)

    generated_queries = [
        f"Query {index}"
        for index in range(1, 8)
    ]

    agent.chain = RunnableLambda(
        lambda _: MultiQueryGeneratorOutput(queries=generated_queries)
    )

    result = agent.generate(
        current_query="Explain RAG retrieval.",
    )

    assert len(result) == 3
    assert [message.content for message in result] == [
        "Query 1",
        "Query 2",
        "Query 3",
    ]


def test_config_rejects_invalid_max_queries():
    with pytest.raises(ValueError):
        MultiQueryGeneratorConfig(max_queries=0)


def test_config_rejects_invalid_temperature():
    with pytest.raises(ValueError):
        MultiQueryGeneratorConfig(temperature=2.5)


def test_config_rejects_invalid_output_tokens():
    with pytest.raises(ValueError):
        MultiQueryGeneratorConfig(max_output_tokens=0)


def test_duplicate_queries_are_rejected():
    with pytest.raises(ValidationError):
        MultiQueryGeneratorOutput(
            queries=[
                "Improve RAG retrieval accuracy",
                "improve rag retrieval accuracy",
            ]
        )


def test_empty_generated_query_is_rejected():
    with pytest.raises(ValidationError):
        MultiQueryGeneratorOutput(
            queries=[
                "Valid query",
                "   ",
            ]
        )


def test_prompt_contains_configured_maximum(make_agent):
    agent = make_agent(
        config=MultiQueryGeneratorConfig(max_queries=4)
    )

    formatted_prompt = agent.prompt.format(
        current_query="Explain RAG.",
        conversation_history=[],
        format_instructions=agent.parser.get_format_instructions(),
    )

    assert "maximum number of generated queries is 4" in formatted_prompt.lower()


@pytest.mark.asyncio
async def test_async_query_generation(make_agent):
    agent = make_agent()

    expected_queries = [
        "BM25 retrieval mechanism",
        "BM25 scoring and ranking",
    ]

    agent.chain = RunnableLambda(
        lambda _: MultiQueryGeneratorOutput(queries=expected_queries)
    )

    result = await agent.agenerate(
        current_query="Explain BM25 retrieval.",
        conversation_history=[
            HumanMessage(content="What is BM25?"),
            AIMessage(content="BM25 is a lexical retrieval algorithm."),
        ],
    )

    assert len(result) == 2
    assert all(isinstance(message, HumanMessage) for message in result)
    assert [message.content for message in result] == expected_queries