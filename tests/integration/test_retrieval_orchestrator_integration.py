from __future__ import annotations

from uuid import uuid4

import pytest

from app.agents.Multi_query_generator.schemas import GeneratedQuery, QueryVersionScope
from app.rag.retrieval.adaptive_k_selector import AdaptiveKSelector
from app.rag.retrieval.candidate_document_generator import CandidateDocument, QueryCandidateResult
from app.rag.retrieval.global_fusion import GlobalResultFusion
from app.services.retrieval.retrieval_service import RetrievalOrchestrator



pytestmark = pytest.mark.integration

def catalogue_entry(version_id: str) -> dict:
    return {
        "document_id": "doc-1",
        "document_version_id": version_id,
        "document_title": "Authorized policy",
        "document_summary": "A test policy document.",
        "version_year": 2026,
        "version_status": "active",
        "last_updated": None,
    }


def candidate(version_id: str) -> CandidateDocument:
    return CandidateDocument(
        document_id="doc-1", document_version_id=version_id,
        document_title="Authorized policy", document_summary="A test policy document.",
        version_year=2026, version_status="active", similarity_score=0.9,
    )


def generated(query: str) -> GeneratedQuery:
    return GeneratedQuery(query=query, version_scope=QueryVersionScope.ACTIVE)


class FakeAuthorization:
    def __init__(self, catalogue):
        self.catalogue, self.calls = catalogue, []

    def get_authorized_document_catalog(self, *, organization_id, user_id):
        self.calls.append((organization_id, user_id))
        return self.catalogue


class ScriptedAgent:
    def __init__(self, batches):
        self.batches, self.calls = list(batches), []

    async def agenerate(self, **kwargs):
        self.calls.append(kwargs)
        return self.batches.pop(0) if self.batches else []


class ScriptedCandidateGenerator:
    def __init__(self, batches):
        self.batches, self.calls = list(batches), []

    async def generate_candidates(self, *, queries, authorized_catalogue, organization_id):
        self.calls.append({
            "queries": list(queries),
            "authorized_catalogue": list(authorized_catalogue),
            "organization_id": organization_id,
        })
        return self.batches.pop(0) if self.batches else []


class RecordingHybridPipeline:
    def __init__(self, results_by_query):
        self.results_by_query, self.calls = results_by_query, []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.results_by_query[kwargs["query"]]


class DeterministicReranker:
    def rerank(self, query, candidates):
        return [
            dict(item, reranker_score=item["metadata"].get("test_reranker_score", 0.95))
            for item in candidates
        ]


def retrieval_result(version_id: str, chunk_index: int, content: str):
    return {
        "result_count": 1,
        "results": [{
            "rank": 1,
            "score": 0.8,
            "page_content": content,
            "metadata": {
                "document_id": "doc-1",
                "document_version_id": version_id,
                "chunk_index": chunk_index,
                "test_reranker_score": 0.95,
            },
        }],
    }


def make_orchestrator(*, catalogue, query_batches, candidate_batches, results_by_query):
    authorization = FakeAuthorization(catalogue)
    agent = ScriptedAgent(query_batches)
    candidate_generator = ScriptedCandidateGenerator(candidate_batches)
    pipeline = RecordingHybridPipeline(results_by_query)
    orchestrator = RetrievalOrchestrator(
        authorization_service=authorization,
        multi_query_agent=agent,
        candidate_document_generator=candidate_generator,
        hybrid_retrieval_pipeline=pipeline,
        global_fusion=GlobalResultFusion(),
        cross_encoder_reranker=DeterministicReranker(),
        adaptive_k_selector=AdaptiveKSelector(
            k_min=2, k_max=5, score_threshold=0.6, max_expansion_rounds=1,
        ),
    )
    return orchestrator, authorization, agent, candidate_generator, pipeline


@pytest.mark.asyncio
async def test_authorized_catalogue_is_the_only_catalogue_passed_to_candidate_generation():
    org_id, user_id = uuid4(), uuid4()
    authorized = [catalogue_entry("authorized-v1")]
    orchestrator, auth, _, candidate_gen, pipeline = make_orchestrator(
        catalogue=authorized,
        query_batches=[[generated("policy query")]],
        candidate_batches=[[
            QueryCandidateResult(
                query="policy query", version_scope=QueryVersionScope.ACTIVE,
                target_versions=[], candidates=[candidate("authorized-v1")],
            )
        ]],
        results_by_query={"policy query": retrieval_result("authorized-v1", 0, "Authorized content")},
    )

    result = await orchestrator.retrieve(
        current_query="What does the policy say?", organization_id=org_id,
        user_id=user_id, top_k=2,
    )

    assert auth.calls == [(org_id, user_id)]
    assert candidate_gen.calls[0]["authorized_catalogue"] == authorized
    assert len(pipeline.calls) == 1
    assert pipeline.calls[0]["candidate_document_version_ids"] == ["authorized-v1"]
    assert pipeline.calls[0]["status"] is None
    assert result["selected_count"] == 1
    assert result["selected_candidates"][0]["metadata"]["document_version_id"] == "authorized-v1"


@pytest.mark.asyncio
async def test_empty_authorized_catalogue_short_circuits_downstream_components():
    orchestrator, _, agent, candidate_gen, pipeline = make_orchestrator(
        catalogue=[], query_batches=[[generated("must not run")]],
        candidate_batches=[[]], results_by_query={},
    )
    result = await orchestrator.retrieve(
        current_query="Find a document", organization_id=uuid4(), user_id=uuid4(),
    )

    assert result["retrieval_reason"] == "no_authorized_document_versions"
    assert result["selected_candidates"] == []
    assert result["branch_count"] == 0
    assert agent.calls == []
    assert candidate_gen.calls == []
    assert pipeline.calls == []


@pytest.mark.asyncio
async def test_real_global_fusion_deduplicates_same_chunk_across_query_branches():
    version_id = "authorized-v1"
    branch_results = [
        QueryCandidateResult(
            query=query, version_scope=QueryVersionScope.ACTIVE,
            target_versions=[], candidates=[candidate(version_id)],
        )
        for query in ("policy wording", "policy requirements")
    ]
    orchestrator, _, _, _, pipeline = make_orchestrator(
        catalogue=[catalogue_entry(version_id)],
        query_batches=[[generated("policy wording"), generated("policy requirements")]],
        candidate_batches=[branch_results],
        results_by_query={
            "policy wording": retrieval_result(version_id, 3, "Same chunk"),
            "policy requirements": retrieval_result(version_id, 3, "Same chunk"),
        },
    )

    result = await orchestrator.retrieve(
        current_query="Explain the policy", organization_id=uuid4(),
        user_id=uuid4(), top_k=2,
    )

    assert len(pipeline.calls) == 2
    assert result["branch_count"] == 2
    assert result["fused_count"] == 1
    assert result["reranked_count"] == 1
    assert result["selected_count"] == 1
    assert len(result["selected_candidates"][0]["provenance"]) == 2


@pytest.mark.asyncio
async def test_candidate_branch_with_retrieval_error_does_not_block_other_branch():
    version_id = "authorized-v1"
    branch_results = [
        QueryCandidateResult(
            query="failed branch", version_scope=QueryVersionScope.ACTIVE,
            target_versions=[], candidates=[candidate(version_id)],
            retrieval_error="summary lookup failed",
        ),
        QueryCandidateResult(
            query="working branch", version_scope=QueryVersionScope.ACTIVE,
            target_versions=[], candidates=[candidate(version_id)],
        ),
    ]
    orchestrator, _, _, _, pipeline = make_orchestrator(
        catalogue=[catalogue_entry(version_id)],
        query_batches=[[generated("failed branch"), generated("working branch")]],
        candidate_batches=[branch_results],
        results_by_query={"working branch": retrieval_result(version_id, 4, "Working content")},
    )

    result = await orchestrator.retrieve(
        current_query="Explain the policy", organization_id=uuid4(),
        user_id=uuid4(), top_k=1,
    )

    assert len(pipeline.calls) == 1
    assert pipeline.calls[0]["query"] == "working branch"
    assert result["branch_count"] == 2
    assert result["branches"][0]["retrieval_error"] == "summary lookup failed"
    assert result["selected_count"] == 1


@pytest.mark.asyncio
async def test_real_adaptive_selector_triggers_expansion_and_stops_when_target_is_met():
    version_id = "authorized-v1"
    initial = [QueryCandidateResult(
        query="initial query", version_scope=QueryVersionScope.ACTIVE,
        target_versions=[], candidates=[candidate(version_id)],
    )]
    expanded = [QueryCandidateResult(
        query="complementary query", version_scope=QueryVersionScope.ACTIVE,
        target_versions=[], candidates=[candidate(version_id)],
    )]
    orchestrator, _, agent, candidate_gen, pipeline = make_orchestrator(
        catalogue=[catalogue_entry(version_id)],
        query_batches=[[generated("initial query")], [generated("complementary query")]],
        candidate_batches=[initial, expanded],
        results_by_query={
            "initial query": retrieval_result(version_id, 0, "First evidence"),
            "complementary query": retrieval_result(version_id, 1, "Second evidence"),
        },
    )

    result = await orchestrator.retrieve(
        current_query="Explain the policy comprehensively", organization_id=uuid4(),
        user_id=uuid4(), top_k=2,
    )

    assert len(agent.calls) == 2
    assert len(candidate_gen.calls) == 2
    assert len(pipeline.calls) == 2
    assert result["expansion"]["rounds_performed"] == 1
    assert result["expansion"]["stop_reason"] == "target_met"
    assert result["selected_count"] == 2
    assert {item["metadata"]["chunk_index"] for item in result["selected_candidates"]} == {0, 1}


@pytest.mark.asyncio
async def test_unexpected_hybrid_pipeline_exception_propagates():
    class BrokenPipeline:
        def search(self, **kwargs):
            raise RuntimeError("Qdrant unavailable")

    version_id = "authorized-v1"
    orchestrator, _, _, _, _ = make_orchestrator(
        catalogue=[catalogue_entry(version_id)],
        query_batches=[[generated("policy query")]],
        candidate_batches=[[
            QueryCandidateResult(
                query="policy query", version_scope=QueryVersionScope.ACTIVE,
                target_versions=[], candidates=[candidate(version_id)],
            )
        ]],
        results_by_query={},
    )
    orchestrator.hybrid_retrieval_pipeline = BrokenPipeline()

    with pytest.raises(RuntimeError, match="Qdrant unavailable"):
        await orchestrator.retrieve(
            current_query="Explain the policy", organization_id=uuid4(),
            user_id=uuid4(), top_k=1,
        )
