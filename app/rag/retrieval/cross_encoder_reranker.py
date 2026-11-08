from __future__ import annotations

import math
from numbers import Real
from typing import Any, Sequence

import requests

from ...core.config import settings


class JinaReranker:
    """Rerank fused retrieval candidates through Jina's hosted reranking API.

    The optional model argument remains available for lightweight unit tests and
    custom local scoring adapters; production defaults to the Jina HTTP API.
    """

    def __init__(
        self,
        model_name: str | None = None,
        batch_size: int = 16,
        max_length: int = 512,
        device: str | None = None,
        model: Any | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        session: Any | None = None,
    ) -> None:
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer.")
        if not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 1:
            raise ValueError("max_length must be a positive integer.")

        self.model_name = (
            model_name or settings.JINA_RERANKER_MODEL
            or "jina-reranker-v2-base-multilingual"
        )
        if not self.model_name.strip():
            raise ValueError("model_name cannot be empty.")
        self.batch_size = batch_size
        # Retained for constructor compatibility; the hosted API controls truncation.
        self.max_length = max_length
        self.device = device
        self.model = model
        self.api_key = api_key if api_key is not None else settings.JINA_API_KEY
        self.base_url = (
            base_url or settings.JINA_API_BASE_URL or "http://127.0.0.1:8090/v1"
        ).rstrip("/")
        self.timeout = (
            settings.JINA_API_TIMEOUT_SECONDS or 120
            if timeout is None else timeout
        )
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or self.timeout <= 0
        ):
            raise ValueError("timeout must be positive.")
        self.session = session or requests.Session()

    def _jina_scores(self, query: str, candidates: list[dict[str, Any]]) -> list[tuple[int, float]]:
        if not self.api_key or not self.api_key.strip():
            raise RuntimeError(
                "JINA_API_KEY is not configured. Set it in backend/.env to the API gateway credential."
            )

        response = self.session.post(
            f"{self.base_url}/rerank",
            headers={
                "Authorization": f"Bearer {self.api_key.strip()}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "query": query,
                "documents": [candidate["page_content"] for candidate in candidates],
                "top_n": len(candidates),
                "return_documents": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            results = response.json()["results"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Jina reranker returned an invalid response.") from exc

        if not isinstance(results, list) or len(results) != len(candidates):
            raise ValueError(
                "Jina reranker returned a result count different from the candidate count."
            )

        scores: list[tuple[int, float]] = []
        seen_indices: set[int] = set()
        for result in results:
            if not isinstance(result, dict):
                raise ValueError("Jina reranker returned an invalid result item.")
            index = result.get("index")
            score = result.get("relevance_score")
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError("Jina reranker returned an invalid candidate index.")
            if index < 0 or index >= len(candidates) or index in seen_indices:
                raise ValueError("Jina reranker returned duplicate or invalid candidate indices.")
            if isinstance(score, bool) or not isinstance(score, Real):
                raise ValueError("Jina reranker scores must be numeric.")
            score = float(score)
            if not math.isfinite(score):
                raise ValueError("Jina reranker scores must be finite.")
            seen_indices.add(index)
            scores.append((index, score))
        return scores

    def rerank(
        self,
        query: str,
        candidates: Sequence[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return candidates sorted by Jina relevance score."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query cannot be empty.")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            raise ValueError("candidates must be a sequence.")
        if top_k is not None and (
            isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1
        ):
            raise ValueError("top_k must be a positive integer.")
        if not candidates:
            return []

        normalized_candidates = [
            self._validate_candidate(candidate, index)
            for index, candidate in enumerate(candidates)
        ]

        if self.model is not None:
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
                values = list(raw_scores)
            except TypeError as exc:
                raise ValueError("Reranker returned invalid scores.") from exc
            if len(values) != len(normalized_candidates):
                raise ValueError(
                    "Reranker returned a score count different from the candidate count."
                )
            indexed_scores = list(enumerate(values))
        else:
            indexed_scores = self._jina_scores(query.strip(), normalized_candidates)

        reranked = []
        for index, raw_score in indexed_scores:
            if isinstance(raw_score, bool) or not isinstance(raw_score, Real):
                raise ValueError("Reranker scores must be numeric.")
            score = float(raw_score)
            if not math.isfinite(score):
                raise ValueError("Reranker scores must be finite.")
            candidate = normalized_candidates[index]
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
        return reranked[:top_k] if top_k is not None else reranked

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


# Backwards-compatible name used by the retrieval orchestrator.
CrossEncoderReranker = JinaReranker
