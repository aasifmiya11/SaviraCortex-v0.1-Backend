
from uuid import uuid4

import pytest

from app.agents.Multi_query_generator.schemas import GeneratedQuery, QueryVersionScope
from app.rag.retrieval.candidate_document_generator import (
    CandidateDocument,
    CandidateDocumentGenerationError,
    QueryCandidateResult,
)
from app.services.retrieval.retrieval_service import RetrievalOrchestrator


class FakeAuthorizationService:
    def __init__(self, catalogue):
        self.catalogue = catalogue

    def get_authorized_document_catalog(self, *, organization_id, user_id):
        assert organization_id is not None
        assert user_id is not None
        return self.catalogue


class FakeMultiQueryAgent:
    def __init__(self):
        self.calls = 0

    async def agenerate(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return [
                GeneratedQuery(query="initial query", version_scope=QueryVersionScope.ACTIVE)
            ]
        return [
            GeneratedQuery(query="expanded query", version_scope=QueryVersionScope.ACTIVE)
        ]


class FakeCandidateGenerator:
    async def generate_candidates(self, *, queries, authorized_catalogue, organization_id):
        return [
            QueryCandidateResult(
                query=query.query,
                version_scope=query.version_scope,
                target_versions=query.target_versions,
                candidates=[
                    CandidateDocument(
                        document_id="document-1",
                        document_version_id=f"version-{query.query}",
                        document_title="Document",
                        document_summary="Summary",
                        version_year=2026,
                        version_status="active",
                        similarity_score=0.9,
                    )
                ],
            )
            for query in queries
        ]


class FakeHybridPipeline:
    def __init__(self):
        self.calls = []

    def search(self, *, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        index = 1 if query == "initial query" else 2
        return {
            "result_count": 1,
            "results": [
                {
                    "rank": 1,
                    "score": 0.9,
                    "page_content": f"content {index}",
                    "metadata": {
                        "document_version_id": f"version-{query}",
                        "chunk_index": index,
                    },
                }
            ],
        }


class FakeReranker:
    def rerank(self, query, candidates):
        return [dict(candidate, reranker_score=0.9) for candidate in candidates]


class FakeSelector:
    k_min = 2
    k_max = 5
    score_threshold = 0.6
    max_expansion_rounds = 1

    def select(self, candidates, expansion_round=0):
        selected = list(candidates[: self.k_max])
        return {
            "selected_candidates": selected,
            "selected_count": len(selected),
            "eligible_count": len(selected),
            "expansion_required": len(selected) < self.k_min and expansion_round < self.max_expansion_rounds,
            "expansion_round": expansion_round,
            "max_expansion_rounds": self.max_expansion_rounds,
            "score_threshold": self.score_threshold,
        }


@pytest.mark.asyncio
async def test_orchestrator_runs_single_pass_and_fuses_all_branches():
    catalogue = [
        {
            "document_id": "document-1",
            "document_version_id": "version-1",
            "document_title": "Document",
            "document_summary": "Summary",
            "version_year": 2026,
            "version_status": "active",
            "last_updated": None,
        }
    ]
    agent = FakeMultiQueryAgent()
    orchestrator = RetrievalOrchestrator(
        authorization_service=FakeAuthorizationService(catalogue),
        multi_query_agent=agent,
        candidate_document_generator=FakeCandidateGenerator(),
        hybrid_retrieval_pipeline=FakeHybridPipeline(),
        global_fusion=__import__("app.rag.retrieval.global_fusion", fromlist=["GlobalResultFusion"]).GlobalResultFusion(),
        cross_encoder_reranker=FakeReranker(),
        adaptive_k_selector=FakeSelector(),
    )

    result = await orchestrator.retrieve(
        current_query="What is the policy?",
        organization_id=uuid4(),
        user_id=uuid4(),
    )

    # Adaptive expansion is intentionally disabled: retrieval performs one
    # candidate-generation and branch-retrieval pass per request.
    assert agent.calls == 1
    assert result["branch_count"] == 1
    assert result["expansion"]["rounds_performed"] == 0
    assert result["expansion"]["stop_reason"] == "disabled_single_pass"
    assert result["selected_count"] == 1
    assert len(result["generated_queries"]) == 1


def test_catalogue_is_split_into_active_and_superseded_models():
    catalogue = [
        {
            "document_id": "d1",
            "document_version_id": "v1",
            "document_title": "Active",
            "document_summary": "Active summary",
            "version_year": 2026,
            "version_status": "active",
        },
        {
            "document_id": "d1",
            "document_version_id": "v0",
            "document_title": "Old",
            "document_summary": "Old summary",
            "version_year": 2025,
            "version_status": "superseded",
        },
    ]

    available = RetrievalOrchestrator._build_available_documents(catalogue)

    assert len(available.active_documents) == 1
    assert len(available.superseded_documents) == 1
    assert available.active_documents[0].version_year == 2026


def test_query_deduplication_is_case_insensitive():
    queries = [
        GeneratedQuery(query="Policy search", version_scope=QueryVersionScope.BOTH),
        GeneratedQuery(query="policy search", version_scope=QueryVersionScope.BOTH),
        GeneratedQuery(query="New angle", version_scope=QueryVersionScope.BOTH),
    ]

    result = RetrievalOrchestrator._deduplicate_queries(queries, set())

    assert [query.query for query in result] == ["Policy search", "New angle"]


class FailingCandidateGenerator:
    async def generate_candidates(self, **kwargs):
        raise CandidateDocumentGenerationError("summary search unavailable")


@pytest.mark.asyncio
async def test_initial_candidate_generation_failure_is_reported_explicitly():
    catalogue = [{
        "document_id": "document-1",
        "document_version_id": "version-1",
        "document_title": "Document",
        "document_summary": "Summary",
        "version_year": 2026,
        "version_status": "active",
    }]
    orchestrator = RetrievalOrchestrator(
        authorization_service=FakeAuthorizationService(catalogue),
        multi_query_agent=FakeMultiQueryAgent(),
        candidate_document_generator=FailingCandidateGenerator(),
        hybrid_retrieval_pipeline=FakeHybridPipeline(),
        global_fusion=__import__(
            "app.rag.retrieval.global_fusion",
            fromlist=["GlobalResultFusion"],
        ).GlobalResultFusion(),
        cross_encoder_reranker=FakeReranker(),
        adaptive_k_selector=FakeSelector(),
    )

    result = await orchestrator.retrieve(
        current_query="What is the policy?",
        organization_id=uuid4(),
        user_id=uuid4(),
    )

    assert result["selected_candidates"] == []
    assert result["retrieval_reason"] == "candidate_generation_failed"
    assert result["expansion"]["stop_reason"] == "candidate_generation_failed"
    assert result["generated_queries"]
    assert result["candidate_generation_error"] == "summary search unavailable"


@pytest.mark.asyncio
async def test_single_pass_does_not_run_expansion_candidate_generation():
    class FailsOnlyOnExpansion:
        def __init__(self):
            self.calls = 0

        async def generate_candidates(self, **kwargs):
            self.calls += 1
            if self.calls > 1:
                raise CandidateDocumentGenerationError(
                    "expansion summary search unavailable"
                )
            return await FakeCandidateGenerator().generate_candidates(**kwargs)

    catalogue = [{
        "document_id": "document-1",
        "document_version_id": "version-1",
        "document_title": "Document",
        "document_summary": "Summary",
        "version_year": 2026,
        "version_status": "active",
    }]
    orchestrator = RetrievalOrchestrator(
        authorization_service=FakeAuthorizationService(catalogue),
        multi_query_agent=FakeMultiQueryAgent(),
        candidate_document_generator=FailsOnlyOnExpansion(),
        hybrid_retrieval_pipeline=FakeHybridPipeline(),
        global_fusion=__import__(
            "app.rag.retrieval.global_fusion",
            fromlist=["GlobalResultFusion"],
        ).GlobalResultFusion(),
        cross_encoder_reranker=FakeReranker(),
        adaptive_k_selector=FakeSelector(),
    )

    result = await orchestrator.retrieve(
        current_query="What is the policy?",
        organization_id=uuid4(),
        user_id=uuid4(),
    )

    # The candidate generator is called only for the initial pass. Because
    # expansion is disabled, its second-call failure must never be triggered.
    assert result["branch_count"] == 1
    assert result["selected_count"] == 1
    assert result["expansion"]["rounds_performed"] == 0
    assert result["expansion"]["stop_reason"] == "disabled_single_pass"
    assert result["candidate_generation_error"] is None


def test_empty_response_stop_reason_matches_actual_reason():
    response = RetrievalOrchestrator._empty_response(
        current_query="question",
        top_k=5,
        candidate_k=10,
        mode="hybrid",
        reason="candidate_generation_failed",
    )

    assert response["retrieval_reason"] == "candidate_generation_failed"
    assert response["expansion"]["stop_reason"] == "candidate_generation_failed"

def test_retrieval_concurrency_requires_positive_integer():
    with pytest.raises(ValueError, match="positive integer"):
        RetrievalOrchestrator(
            authorization_service=FakeAuthorizationService([]),
            multi_query_agent=FakeMultiQueryAgent(),
            candidate_document_generator=FakeCandidateGenerator(),
            hybrid_retrieval_pipeline=FakeHybridPipeline(),
            global_fusion=__import__(
                "app.rag.retrieval.global_fusion",
                fromlist=["GlobalResultFusion"],
            ).GlobalResultFusion(),
            cross_encoder_reranker=FakeReranker(),
            adaptive_k_selector=FakeSelector(),
            retrieval_concurrency=1.5,
        )



@pytest.mark.asyncio
async def test_orchestrator_forwards_chunk_exclusions_to_hybrid_pipeline():
    catalogue = [
        {
            "document_id": "document-1",
            "document_version_id": "version-1",
            "document_title": "Document",
            "document_summary": "Summary",
            "version_year": 2026,
            "version_status": "active",
        }
    ]
    hybrid_pipeline = FakeHybridPipeline()
    orchestrator = RetrievalOrchestrator(
        authorization_service=FakeAuthorizationService(catalogue),
        multi_query_agent=FakeMultiQueryAgent(),
        candidate_document_generator=FakeCandidateGenerator(),
        hybrid_retrieval_pipeline=hybrid_pipeline,
        global_fusion=__import__(
            "app.rag.retrieval.global_fusion",
            fromlist=["GlobalResultFusion"],
        ).GlobalResultFusion(),
        cross_encoder_reranker=FakeReranker(),
        adaptive_k_selector=FakeSelector(),
    )

    await orchestrator.retrieve(
        current_query="What is the policy?",
        organization_id=uuid4(),
        user_id=uuid4(),
        exclude=True,
        excluded_chunk_ids=["version-previous:12"],
    )

    assert hybrid_pipeline.calls
    assert all(call["exclude"] is True for call in hybrid_pipeline.calls)
    assert all(
        call["excluded_chunk_ids"] == ["version-previous:12"]
        for call in hybrid_pipeline.calls
    )
