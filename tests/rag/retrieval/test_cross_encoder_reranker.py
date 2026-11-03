import pytest

from app.rag.retrieval.cross_encoder_reranker import CrossEncoderReranker


class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        return self.scores


def _candidate(chunk_id, content, rank):
    return {
        "chunk_id": chunk_id,
        "global_rank": rank,
        "global_rrf_score": 0.02,
        "page_content": content,
        "metadata": {
            "document_version_id": "version-1",
            "chunk_index": rank,
        },
        "provenance": [],
    }


def test_reranker_sorts_by_cross_encoder_score():
    model = FakeCrossEncoder([0.2, 0.9, 0.5])
    reranker = CrossEncoderReranker(model=model)
    candidates = [
        _candidate("chunk-1", "first", 1),
        _candidate("chunk-2", "second", 2),
        _candidate("chunk-3", "third", 3),
    ]

    result = reranker.rerank("search query", candidates)

    assert [item["chunk_id"] for item in result] == [
        "chunk-2",
        "chunk-3",
        "chunk-1",
    ]
    assert [item["reranker_score"] for item in result] == [0.9, 0.5, 0.2]
    assert all(
        item["global_rrf_score"] == 0.02
        for item in result
    )
    assert model.calls[0][0] == [
        ("search query", "first"),
        ("search query", "second"),
        ("search query", "third"),
    ]


def test_reranker_preserves_input_candidates_and_supports_top_k():
    model = FakeCrossEncoder([0.8, 0.7])
    reranker = CrossEncoderReranker(model=model)
    candidates = [
        _candidate("chunk-1", "first", 1),
        _candidate("chunk-2", "second", 2),
    ]

    result = reranker.rerank("query", candidates, top_k=1)

    assert len(result) == 1
    assert "reranker_score" not in candidates[0]
    assert result[0]["metadata"] is not candidates[0]["metadata"]
    assert result[0]["provenance"] is not candidates[0]["provenance"]


def test_empty_candidates_do_not_call_model():
    model = FakeCrossEncoder([])
    assert CrossEncoderReranker(model=model).rerank("query", []) == []
    assert model.calls == []


@pytest.mark.parametrize(
    ("query", "candidates", "message"),
    [
        ("", [], "query"),
        ("query", "invalid", "candidates"),
        ("query", [{}], "missing fields"),
    ],
)
def test_reranker_validates_input(query, candidates, message):
    with pytest.raises(ValueError, match=message):
        CrossEncoderReranker(model=FakeCrossEncoder([])).rerank(
            query,
            candidates,
        )


def test_reranker_rejects_mismatched_score_count():
    candidate = _candidate("chunk-1", "content", 1)
    reranker = CrossEncoderReranker(model=FakeCrossEncoder([]))

    with pytest.raises(ValueError, match="score count"):
        reranker.rerank("query", [candidate])


def test_reranker_rejects_non_finite_scores():
    candidate = _candidate("chunk-1", "content", 1)
    reranker = CrossEncoderReranker(model=FakeCrossEncoder([float("nan")]))

    with pytest.raises(ValueError, match="finite"):
        reranker.rerank("query", [candidate])
