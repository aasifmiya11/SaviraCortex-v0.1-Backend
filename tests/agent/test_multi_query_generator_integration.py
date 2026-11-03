import pytest

from langchain_core.messages import HumanMessage, AIMessage

from app.agents.Multi_query_generator import (
    MultiQueryGeneratorAgent,
    MultiQueryGeneratorConfig,
)


@pytest.mark.integration
def test_real_multi_query_generation():

    config = MultiQueryGeneratorConfig(
        max_queries=6,
        temperature=0.2,
        max_output_tokens=1500,
    )

    agent = MultiQueryGeneratorAgent(config=config)

    history = [
        HumanMessage(content="What is Retrieval-Augmented Generation?"),
        AIMessage(
            content=(
                "RAG combines information retrieval with "
                "language generation to ground model responses."
            )
        ),
        HumanMessage(content="Explain its retrieval architecture."),
        AIMessage(
            content=(
                "A typical retrieval architecture includes "
                "query processing, retrieval, and context construction."
            )
        ),
    ]

    result = agent.generate(
        current_query="How can we improve its retrieval accuracy?",
        conversation_history=history,
    )

    assert isinstance(result, list)
    assert len(result) >= 1
    assert len(result) <= config.max_queries

    assert all(
        isinstance(message, HumanMessage)
        for message in result
    )

    queries = [message.content for message in result]

    assert all(query.strip() for query in queries)
    assert len(queries) == len(set(query.casefold() for query in queries))


@pytest.mark.integration
def test_real_simple_query_generation():

    agent = MultiQueryGeneratorAgent()

    result = agent.generate(
        current_query="What is cosine similarity?",
        conversation_history=[],
    )

    assert isinstance(result, list)
    assert 1 <= len(result) <= agent.config.max_queries

    assert all(
        isinstance(message, HumanMessage)
        for message in result
    )

    assert all(message.content.strip() for message in result)