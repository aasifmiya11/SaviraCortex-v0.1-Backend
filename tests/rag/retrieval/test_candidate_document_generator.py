import pytest

from app.agents.Multi_query_generator.schemas import (
    GeneratedQuery,
    QueryVersionScope,
)
from app.rag.retrieval.candidate_document_generator import (
    CandidateDocumentGenerator,
)


class FakeSummaryStore:

    def __init__(self, results):
        self.results = results
        self.calls = []

    def search_similar_summaries(
        self,
        summary,
        limit=20,
        *,
        organization_id,
    ):
        self.calls.append({
            "query": summary,
            "limit": limit,
            "organization_id": organization_id,
        })

        return self.results.get(summary, [])


@pytest.mark.asyncio
async def test_candidate_generation_filters_authorization_and_scope():

    store = FakeSummaryStore({
        "active policy": [
            {
                "document_id": "doc-1",
                "document_version_id": "version-1",
                "status": "superseded",  # Intentionally stale.
                "similarity_score": 0.85,
            },
            {
                "document_id": "doc-2",
                "document_version_id": "unauthorized-version",
                "similarity_score": 0.95,
            },
            {
                "document_id": "doc-3",
                "document_version_id": "version-3",
                "similarity_score": 0.30,
            },
        ]
    })

    generator = CandidateDocumentGenerator(
        summary_store=store,
        similarity_threshold=0.40,
    )

    catalogue = [
        {
            "document_id": "doc-1",
            "document_version_id": "version-1",
            "document_title": "Privacy Policy",
            "document_summary": "Privacy requirements.",
            "version_year": 2026,
            "version_status": "active",
            "last_updated": "2026-01-01",
        }
    ]

    queries = [
        GeneratedQuery(
            query="active policy",
            version_scope=QueryVersionScope.ACTIVE,
            target_versions=[],
        )
    ]

    results = await generator.generate_candidates(
        queries=queries,
        authorized_catalogue=catalogue,
        organization_id="org-1",
    )

    assert len(results) == 1
    assert len(results[0].candidates) == 1

    candidate = results[0].candidates[0]

    assert candidate.document_version_id == "version-1"
    assert candidate.version_status == "active"
    assert candidate.similarity_score == 0.85


@pytest.mark.asyncio
async def test_target_version_filter():

    store = FakeSummaryStore({
        "policy": [
            {
                "document_id": "doc-1",
                "document_version_id": "version-2025",
                "similarity_score": 0.90,
            },
            {
                "document_id": "doc-1",
                "document_version_id": "version-2026",
                "similarity_score": 0.85,
            },
        ]
    })

    generator = CandidateDocumentGenerator(store)

    catalogue = [
        {
            "document_id": "doc-1",
            "document_version_id": "version-2025",
            "document_title": "Policy",
            "document_summary": "Older policy.",
            "version_year": 2025,
            "version_status": "superseded",
            "last_updated": "2025-01-01",
        },
        {
            "document_id": "doc-1",
            "document_version_id": "version-2026",
            "document_title": "Policy",
            "document_summary": "Current policy.",
            "version_year": 2026,
            "version_status": "active",
            "last_updated": "2026-01-01",
        },
    ]

    queries = [
        GeneratedQuery(
            query="policy",
            version_scope=QueryVersionScope.SUPERSEDED,
            target_versions=[2025],
        )
    ]

    results = await generator.generate_candidates(
        queries=queries,
        authorized_catalogue=catalogue,
        organization_id="org-1",
    )

    assert len(results[0].candidates) == 1
    assert results[0].candidates[0].version_year == 2025


@pytest.mark.asyncio
async def test_candidates_remain_separate_across_queries():

    store = FakeSummaryStore({
        "query one": [
            {
                "document_id": "doc-1",
                "document_version_id": "version-1",
                "similarity_score": 0.90,
            }
        ],
        "query two": [
            {
                "document_id": "doc-1",
                "document_version_id": "version-1",
                "similarity_score": 0.88,
            }
        ],
    })

    generator = CandidateDocumentGenerator(store)

    catalogue = [
        {
            "document_id": "doc-1",
            "document_version_id": "version-1",
            "document_title": "Policy",
            "document_summary": "Policy summary.",
            "version_year": 2026,
            "version_status": "active",
            "last_updated": "2026-01-01",
        }
    ]

    queries = [
        GeneratedQuery(
            query="query one",
            version_scope=QueryVersionScope.ACTIVE,
        ),
        GeneratedQuery(
            query="query two",
            version_scope=QueryVersionScope.ACTIVE,
        ),
    ]

    results = await generator.generate_candidates(
        queries=queries,
        authorized_catalogue=catalogue,
        organization_id="org-1",
    )

    assert len(results) == 2

    assert results[0].candidates[0].document_version_id == "version-1"
    assert results[1].candidates[0].document_version_id == "version-1"

    assert len(store.calls) == 2
    assert all(call["limit"] == 20 for call in store.calls)