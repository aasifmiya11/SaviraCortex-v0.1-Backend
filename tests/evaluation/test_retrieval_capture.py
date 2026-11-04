from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.retrieval_capture import (
    RecordingCandidateDocumentGenerator,
    RecordingCrossEncoderReranker,
    RecordingHybridRetrievalPipeline,
    serialize_branch,
    serialize_rerank_pass,
)


class FakePipeline:
    def search(self, **kwargs):
        return {
            "query": kwargs["query"],
            "mode": kwargs["mode"],
            "top_k": kwargs["top_k"],
            "candidate_k": kwargs["candidate_k"],
            "result_count": 1,
            "results": [{
                "rank": 1,
                "score": 0.81,
                "page_content": "Example evidence",
                "metadata": {
                    "document_id": "doc-1",
                    "document_version_id": "version-1",
                    "chunk_index": 7,
                    "source_filename": "example.pdf",
                    "page": "3",
                },
            }],
        }


class FakeReranker:
    def rerank(self, query, candidates, top_k=None):
        return [
            {
                **item,
                "metadata": dict(item["metadata"]),
                "provenance": list(item["provenance"]),
                "reranker_score": 0.93,
            }
            for item in candidates
        ]


def test_recording_pipeline_returns_original_result_and_captures_branch():
    recorder = RecordingHybridRetrievalPipeline(FakePipeline())
    result = recorder.search(query="example", mode="hybrid", top_k=10, candidate_k=20)
    assert result["result_count"] == 1
    captured = recorder.snapshot(["example"])
    assert captured[0]["query"] == "example"
    assert captured[0]["results"][0]["rank"] == 1


def test_recording_reranker_captures_fused_and_reranked_candidates():
    candidate = {
        "chunk_id": "version-1:7",
        "global_rank": 2,
        "global_rrf_score": 0.03,
        "page_content": "Example evidence",
        "metadata": {"document_version_id": "version-1", "chunk_index": 7},
        "provenance": [],
    }
    recorder = RecordingCrossEncoderReranker(FakeReranker())
    result = recorder.rerank("example", [candidate])
    assert result[0]["reranker_score"] == 0.93
    assert recorder.snapshot()[0]["fused_count"] == 1
    assert recorder.snapshot()[0]["reranked_count"] == 1


def test_serializers_attach_stable_chunk_and_qdrant_point_ids():
    lookup = {
        "version-1:7": {
            "chunk_id": "version-1:7",
            "qdrant_point_id": "point-uuid",
            "source_filename": "example.pdf",
            "page": "3",
        }
    }
    raw = {
        "query": "example",
        "mode": "hybrid",
        "top_k": 10,
        "candidate_k": 20,
        "result_count": 1,
        "results": [{
            "rank": 1,
            "score": 0.81,
            "page_content": "Example evidence",
            "metadata": {"document_version_id": "version-1", "chunk_index": 7},
        }],
    }
    branch = serialize_branch(raw, lookup)
    assert branch["results"][0]["chunk_id"] == "version-1:7"
    assert branch["results"][0]["qdrant_point_id"] == "point-uuid"

    rerank = serialize_rerank_pass({
        "query": "example",
        "fused_candidates": [{
            "chunk_id": "version-1:7",
            "global_rank": 1,
            "page_content": "Example evidence",
            "metadata": {"document_version_id": "version-1", "chunk_index": 7},
            "provenance": [],
        }],
        "reranked_candidates": [{
            "chunk_id": "version-1:7",
            "global_rank": 1,
            "reranker_score": 0.93,
            "page_content": "Example evidence",
            "metadata": {"document_version_id": "version-1", "chunk_index": 7},
            "provenance": [],
        }],
    }, lookup)
    assert rerank["reranked_candidates"][0]["reranked_rank"] == 1
    assert rerank["reranked_candidates"][0]["reranker_score"] == 0.93


class FakeCandidateGenerator:
    async def generate_candidates(self, **kwargs):
        return [{"query": "example", "candidates": [{"document_version_id": "v1"}]}]


def test_recording_candidate_generator_captures_document_candidates():
    recorder = RecordingCandidateDocumentGenerator(FakeCandidateGenerator())
    result = asyncio.run(recorder.generate_candidates(queries=[]))
    assert result[0]["query"] == "example"
    assert recorder.snapshot()[0][0]["candidates"][0]["document_version_id"] == "v1"
