from __future__ import annotations

import math
from numbers import Real
from typing import Any, Sequence

from sentence_transformers import CrossEncoder


class CrossEncoderReranker:
    """Rerank globally fused retrieval candidates with a cross-encoder."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        batch_size: int = 16,
        max_length: int = 512,
        device: str | None = None,
        model: Any | None = None,
    ) -> None:
        if not model_name or not model_name.strip():
            raise ValueError("model_name cannot be empty.")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise ValueError("batch_size must be a positive integer.")
        if (
            isinstance(max_length, bool)
            or not isinstance(max_length, int)
            or max_length < 1
        ):
            raise ValueError("max_length must be a positive integer.")

        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self.model = model or CrossEncoder(
            model_name,
            max_length=max_length,
            device=device,
        )

    def rerank(
        self,
        query: str,
        candidates: Sequence[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return candidates sorted by cross-encoder relevance score."""

        if not isinstance(query, str) or not query.strip():
            raise ValueError("query cannot be empty.")
        if not isinstance(candidates, Sequence) or isinstance(
            candidates,
            (str, bytes),
        ):
            raise ValueError("candidates must be a sequence.")
        if top_k is not None and (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or top_k < 1
        ):
            raise ValueError("top_k must be a positive integer.")
        if not candidates:
            return []

        normalized_candidates = [
            self._validate_candidate(candidate, index)
            for index, candidate in enumerate(candidates)
        ]
        pairs = [
            (query.strip(), candidate["page_content"])
            for candidate in normalized_candidates
        ]
        raw_scores = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        try:
            scores = list(raw_scores)
        except TypeError as exc:
            raise ValueError("Cross-encoder returned invalid scores.") from exc

        if len(scores) != len(normalized_candidates):
            raise ValueError(
                "Cross-encoder returned a score count different from "
                "the candidate count."
            )

        reranked = []
        for candidate, score in zip(normalized_candidates, scores):
            if isinstance(score, bool) or not isinstance(score, Real):
                raise ValueError("Cross-encoder scores must be numeric.")
            score = float(score)
            if not math.isfinite(score):
                raise ValueError("Cross-encoder scores must be finite.")

            enriched = dict(candidate)
            enriched["metadata"] = dict(candidate.get("metadata") or {})
            enriched["provenance"] = list(candidate.get("provenance") or [])
            enriched["reranker_score"] = score
            reranked.append(enriched)

        reranked.sort(
            key=lambda candidate: (
                -candidate["reranker_score"],
                candidate.get("global_rank", float("inf")),
                str(candidate.get("chunk_id", "")),
            )
        )
        if top_k is not None:
            reranked = reranked[:top_k]
        return reranked

    @staticmethod
    def _validate_candidate(
        candidate: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            raise ValueError(f"Candidate {index} must be a dictionary.")

        required_fields = {
            "chunk_id",
            "page_content",
            "metadata",
            "global_rank",
            "global_rrf_score",
            "provenance",
        }
        missing = required_fields - candidate.keys()
        if missing:
            raise ValueError(
                f"Candidate {index} is missing fields: {sorted(missing)}"
            )
        if not isinstance(candidate["page_content"], str):
            raise ValueError(f"Candidate {index} page_content must be a string.")
        if not candidate["page_content"].strip():
            raise ValueError(f"Candidate {index} page_content cannot be empty.")
        return candidate
