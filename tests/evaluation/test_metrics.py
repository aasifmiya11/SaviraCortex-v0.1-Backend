from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.metrics import retrieval_metrics, evaluate_ranked_lists


def test_retrieval_metrics_use_fixed_precision_denominator_and_relevant_count():
    metrics = retrieval_metrics(
        ranked_chunk_ids=["irrelevant", "relevant-a", "relevant-b"],
        qrels={"relevant-a": 3, "relevant-b": 1},
        k_values=(1, 2, 5),
    )
    assert metrics["precision@1"] == 0.0
    assert metrics["recall@1"] == 0.0
    assert metrics["precision@2"] == 0.5
    assert metrics["recall@2"] == 0.5
    assert metrics["mrr@2"] == 0.5
    assert metrics["precision@5"] == 0.4
    assert metrics["recall@5"] == 1.0
    assert metrics["mrr@5"] == 0.5


def test_ndcg_rewards_graded_relevant_chunks_at_the_top():
    ideal = retrieval_metrics(["high", "low"], {"high": 3, "low": 1}, (2,))
    reversed_order = retrieval_metrics(["low", "high"], {"high": 3, "low": 1}, (2,))
    assert ideal["ndcg@2"] == pytest.approx(1.0)
    assert reversed_order["ndcg@2"] < ideal["ndcg@2"]


def test_duplicate_ranked_chunk_ids_are_counted_once():
    metrics = retrieval_metrics(["relevant", "relevant"], {"relevant": 2}, (2,))
    assert metrics["precision@2"] == 0.5
    assert metrics["recall@2"] == 1.0
    assert metrics["mrr@2"] == 1.0


def test_evaluate_both_full_reranked_and_adaptive_selected_lists():
    rows = [{
        "question_id": "Q-1",
        "question": {"text": "What is X?"},
        "retrieval": {
            "reranked_candidates": [{"chunk_id": "wrong"}, {"chunk_id": "right"}],
            "selected_candidates": [{"chunk_id": "right"}],
        },
    }]
    result = evaluate_ranked_lists(rows, {"Q-1": {"right": 2}}, (1, 2))
    assert result["evaluated_question_count"] == 1
    assert result["macro_average"]["full_reranked_list"]["recall@1"] == 0.0
    assert result["macro_average"]["adaptive_selected_list"]["recall@1"] == 1.0


def test_metrics_reject_empty_qrels_and_invalid_grades():
    with pytest.raises(ValueError, match="At least one relevant chunk"):
        retrieval_metrics(["chunk"], {}, (1,))
    with pytest.raises(ValueError, match="integer from 0 to 3"):
        retrieval_metrics(["chunk"], {"chunk": 4}, (1,))
