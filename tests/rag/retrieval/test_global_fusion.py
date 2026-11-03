import pytest

from app.rag.retrieval.global_fusion import GlobalResultFusion


def make_result(version, chunk, rank, score=0.5):
    return {
        "rank": rank,
        "score": score,
        "page_content": f"content-{version}-{chunk}",
        "metadata": {
            "document_id": f"doc-{version}",
            "document_version_id": version,
            "chunk_index": chunk,
        },
    }


def make_branch(query, results):
    return {
        "query": query,
        "mode": "hybrid",
        "result_count": len(results),
        "results": results,
    }


def test_global_fusion_deduplicates_identical_chunks():
    fusion = GlobalResultFusion()
    result = fusion.fuse([
        make_branch("query one", [
            make_result("v1", 0, 1),
            make_result("v1", 1, 2),
        ]),
        make_branch("query two", [
            make_result("v1", 1, 1, 0.9),
            make_result("v2", 0, 2),
        ]),
    ])

    assert len(result) == 3
    duplicate = next(item for item in result if item["chunk_id"] == "v1:1")
    assert len(duplicate["provenance"]) == 2
    assert [item["query"] for item in duplicate["provenance"]] == [
        "query one",
        "query two",
    ]


def test_global_rrf_uses_branch_rank_and_retains_branch_score():
    result = GlobalResultFusion().fuse([
        make_branch("first", [make_result("v1", 0, 1, 0.1)]),
        make_branch("second", [make_result("v2", 0, 1, 0.9)]),
    ], rrf_k=1)

    assert result[0]["global_rrf_score"] == pytest.approx(0.5)
    assert result[0]["provenance"][0]["score"] in {0.1, 0.9}


def test_global_fusion_limits_results_and_uses_fallback_identity():
    first = {
        "rank": 1,
        "score": 0.5,
        "page_content": "same content",
        "metadata": {"source": "file.pdf", "page": 1},
    }
    second = {**first, "rank": 2}

    result = GlobalResultFusion().fuse([
        make_branch("one", [first]),
        make_branch("two", [second]),
    ], top_k=1)

    assert len(result) == 1
    assert result[0]["chunk_id"] == "file.pdf:1:same content"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"branch_results": "invalid"}, "branch_results"),
        ({"branch_results": [], "top_k": 0}, "top_k"),
        ({"branch_results": [], "rrf_k": 0}, "rrf_k"),
    ],
)
def test_global_fusion_validates_arguments(kwargs, message):
    with pytest.raises(ValueError, match=message):
        GlobalResultFusion().fuse(**kwargs)


def test_global_fusion_rejects_malformed_branch():
    with pytest.raises(ValueError, match="results list"):
        GlobalResultFusion().fuse([{"query": "missing results"}])
