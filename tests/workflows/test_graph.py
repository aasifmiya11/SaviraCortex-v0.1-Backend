from uuid import uuid4

import pytest

from app.agents.Evidence_evaluator.schemas import EvidenceEvaluation
from app.agents.Generation.schemas import (
    AnswerSegment,
    GenerationOutput,
    GenerationStatus,
)
from app.validation.schemas import GenerationValidationResult
from app.workflows.rag.graph import create_rag_graph


class FakeRetriever:
    def __init__(self):
        self.calls = []

    async def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "selected_candidates": [
                {
                    "chunk_id": "doc-version:0",
                    "page_content": "The company provides 20 days of annual leave.",
                    "metadata": {"document_id": "doc"},
                }
            ],
            "selected_count": 1,
            "eligible_count": 1,
            "fused_count": 1,
            "reranked_count": 1,
            "branch_count": 1,
            "expansion": {},
        }


class FakeEvaluator:
    async def aevaluate(self, **kwargs):
        return EvidenceEvaluation(is_sufficient=True, missing_information=[])


class FakeExpansionAgent:
    async def aexpand(self, **kwargs):
        raise AssertionError("Expansion must not run for sufficient evidence.")


class FakeCompressionAgent:
    def __init__(self):
        self.calls = 0

    def estimate_token_count(self, query, documents):
        return 100

    async def acompress(self, current_query, retrieved_documents):
        self.calls += 1
        return list(retrieved_documents)


class FakeGenerationAgent:
    async def agenerate(self, **kwargs):
        return GenerationOutput(
            status=GenerationStatus.ANSWERED,
            segments=[
                AnswerSegment(
                    text="The annual leave entitlement is 20 days.",
                    citations=["E1"],
                )
            ],
        )


class FakeValidator:
    def validate_generation_output(self, output, retrieved_documents):
        return GenerationValidationResult(
            is_valid=True,
            output=output,
            citations=[],
        )


def build_graph(retriever=None, compression=None):
    return create_rag_graph(
        retriever=retriever or FakeRetriever(),
        evaluator=FakeEvaluator(),
        retrieval_expansion_agent=FakeExpansionAgent(),
        context_compression_agent=compression or FakeCompressionAgent(),
        generation_agent=FakeGenerationAgent(),
        validator=FakeValidator(),
    )


@pytest.mark.asyncio
async def test_graph_compiles_and_runs_valid_query_to_static_validation():
    retriever = FakeRetriever()
    compression = FakeCompressionAgent()
    graph = build_graph(retriever, compression)

    result = await graph.ainvoke(
        {
            "query": "How many annual leave days are provided?",
            "organization_id": uuid4(),
            "user_id": uuid4(),
        }
    )

    assert result["is_valid"] is True
    assert result["retrieval_attempt"] == 1
    assert result["context_compressed"] is False
    assert compression.calls == 0
    assert result["generation_output"].status == GenerationStatus.ANSWERED
    assert result["validation_result"].is_valid is True
    assert len(retriever.calls) == 1
    assert retriever.calls[0]["exclude"] is False


@pytest.mark.asyncio
async def test_graph_ends_after_invalid_input_without_retrieval():
    retriever = FakeRetriever()
    graph = build_graph(retriever)

    result = await graph.ainvoke(
        {
            "query": "!!!",
            "organization_id": uuid4(),
            "user_id": uuid4(),
        }
    )

    assert result["is_valid"] is False
    assert result["validation_error"]
    assert retriever.calls == []
    assert "generation_output" not in result


@pytest.mark.asyncio
async def test_graph_invokes_compression_only_above_15_documents():
    retriever = FakeRetriever()

    async def retrieve_many(**kwargs):
        retriever.calls.append(kwargs)
        return {
            "selected_candidates": [
                {
                    "chunk_id": f"doc-version:{index}",
                    "page_content": f"Evidence {index}",
                    "metadata": {},
                }
                for index in range(16)
            ],
            "selected_count": 16,
            "eligible_count": 16,
            "fused_count": 16,
            "reranked_count": 16,
            "branch_count": 1,
            "expansion": {},
        }

    retriever.retrieve = retrieve_many
    compression = FakeCompressionAgent()
    graph = build_graph(retriever, compression)

    result = await graph.ainvoke(
        {
            "query": "Summarize the relevant policy.",
            "organization_id": uuid4(),
            "user_id": uuid4(),
        }
    )

    assert compression.calls == 1
    assert result["context_compressed"] is True
    assert len(result["context_documents"]) == 16


class AlwaysInsufficientEvaluator:
    async def aevaluate(self, **kwargs):
        return EvidenceEvaluation(
            is_sufficient=False,
            missing_information=["The policy's exception conditions are missing."],
        )


class CountingExpansionAgent:
    def __init__(self):
        self.calls = 0

    async def aexpand(self, **kwargs):
        from app.agents.Retrieval_expansion.schemas import RetrievalExpansionOutput

        self.calls += 1
        return RetrievalExpansionOutput(
            rewritten_query=f"Find policy exception details, attempt {self.calls}",
            hypothetical_answer="A hypothetical description of possible policy exceptions.",
        )


@pytest.mark.asyncio
async def test_graph_performs_three_total_retrieval_attempts_and_two_expansions():
    retriever = FakeRetriever()
    expansion = CountingExpansionAgent()
    graph = create_rag_graph(
        retriever=retriever,
        evaluator=AlwaysInsufficientEvaluator(),
        retrieval_expansion_agent=expansion,
        context_compression_agent=FakeCompressionAgent(),
        generation_agent=FakeGenerationAgent(),
        validator=FakeValidator(),
    )

    result = await graph.ainvoke(
        {
            "query": "Explain the annual leave policy and its exceptions.",
            "organization_id": uuid4(),
            "user_id": uuid4(),
        }
    )

    assert result["retrieval_attempt"] == 3
    assert len(retriever.calls) == 3
    assert expansion.calls == 2
    assert [call["exclude"] for call in retriever.calls] == [False, True, True]
    assert result["generation_output"].status == GenerationStatus.ANSWERED
