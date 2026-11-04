import pytest

from app.agents.Retrieval_expansion import RetrievalExpansionOutput
from app.workflows.rag.nodes.retrieval_expansion import (
    create_retrieval_expansion_node,
)


class FakeRetrievalExpansionAgent:
    def __init__(self, result):
        self.result = result
        self.received = None

    async def aexpand(
        self,
        original_query,
        missing_information,
        retrieved_documents=None,
        conversation_history=None,
        current_retrieval_query=None,
    ):
        self.received = {
            "original_query": original_query,
            "current_retrieval_query": current_retrieval_query,
            "missing_information": missing_information,
            "retrieved_documents": retrieved_documents,
            "conversation_history": conversation_history,
        }
        return self.result


@pytest.mark.asyncio
async def test_retrieval_expansion_node_injects_agent_and_maps_outputs():
    documents = [
        {"chunk_id": "chunk-1", "page_content": "Annual leave is 20 days."}
    ]
    history = []
    agent = FakeRetrievalExpansionAgent(
        RetrievalExpansionOutput(
            rewritten_query="Annual leave approval workflow and authority",
            hypothetical_answer=(
                "The policy describes the leave request workflow and "
                "the role responsible for approving requests."
            ),
        )
    )
    node = create_retrieval_expansion_node(agent)

    updates = await node(
        {
            "query": "How many leave days and who approves them?",
            "organization_id": "org-id",
            "user_id": "user-id",
            "context": history,
            "retrieved_documents": documents,
            "missing_information": ["The approval workflow and authority."],
        }
    )

    assert agent.received == {
        "original_query": "How many leave days and who approves them?",
        "current_retrieval_query": "How many leave days and who approves them?",
        "missing_information": ["The approval workflow and authority."],
        "retrieved_documents": documents,
        "conversation_history": history,
    }
    assert updates == {
        "rewritten_query": "Annual leave approval workflow and authority",
        "hypothetical_answer": (
            "The policy describes the leave request workflow and "
            "the role responsible for approving requests."
        ),
    }


@pytest.mark.asyncio
async def test_node_uses_previous_rewritten_query_as_current_retrieval_query():
    agent = FakeRetrievalExpansionAgent(
        RetrievalExpansionOutput(
            rewritten_query="A more focused query",
            hypothetical_answer="A hypothetical answer passage.",
        )
    )
    node = create_retrieval_expansion_node(agent)

    await node(
        {
            "query": "Original question",
            "rewritten_query": "Previous expanded retrieval query",
            "missing_information": ["Another missing requirement."],
        }
    )

    assert agent.received["original_query"] == "Original question"
    assert (
        agent.received["current_retrieval_query"]
        == "Previous expanded retrieval query"
    )


@pytest.mark.asyncio
async def test_node_defaults_documents_and_history_to_empty():
    agent = FakeRetrievalExpansionAgent(
        RetrievalExpansionOutput(
            rewritten_query="Focused retrieval query",
            hypothetical_answer="Hypothetical retrieval passage.",
        )
    )
    node = create_retrieval_expansion_node(agent)

    await node(
        {
            "query": "Original question",
            "missing_information": ["Missing requirement."],
        }
    )

    assert agent.received["retrieved_documents"] == []
    assert agent.received["conversation_history"] is None
