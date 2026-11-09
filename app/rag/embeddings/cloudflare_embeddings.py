"""Cloudflare Workers AI embeddings adapter implementing LangChain's Embeddings protocol."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import requests
from langchain_core.embeddings import Embeddings

from ...core.config import settings


class CloudflareEmbeddingClient(Embeddings):
    """Generate Qwen3 vectors through the private Cloudflare gateway route."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        batch_size: int | None = None,
        session: Any | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.JINA_API_KEY
        self.base_url = (
            base_url or settings.JINA_API_BASE_URL or "http://127.0.0.1:8090/v1"
        ).rstrip("/")
        self.model_name = settings.CLOUDFLARE_EMBEDDING_MODEL
        self.dimensions = settings.CLOUDFLARE_EMBEDDING_DIMENSIONS
        if self.dimensions < 1:
            raise ValueError("CLOUDFLARE_EMBEDDING_DIMENSIONS must be positive.")
        self.timeout = (
            settings.JINA_API_TIMEOUT_SECONDS or 120 if timeout is None else timeout
        )
        self.batch_size = (
            settings.JINA_EMBEDDING_BATCH_SIZE or 64 if batch_size is None else batch_size
        )
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int) or self.batch_size < 1:
            raise ValueError("batch_size must be a positive integer.")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ValueError("timeout must be positive.")
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        if not self.api_key or not self.api_key.strip():
            raise RuntimeError(
                "JINA_API_KEY is not configured. Set it to the API gateway credential in backend/.env."
            )
        return {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json",
        }

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self.session.post(
            f"{self.base_url}/cloudflare/embeddings",
            headers=self._headers(),
            json={"input": texts},
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            items = response.json()["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Cloudflare embeddings API returned an invalid response.") from exc
        if not isinstance(items, list) or len(items) != len(texts):
            raise RuntimeError(
                "Cloudflare embeddings API returned a vector count different from the input count."
            )
        ordered: list[list[float] | None] = [None] * len(texts)
        for item in items:
            if not isinstance(item, dict):
                raise RuntimeError("Cloudflare embeddings API returned an invalid vector item.")
            index, vector = item.get("index"), item.get("embedding")
            if isinstance(index, bool) or not isinstance(index, int):
                raise RuntimeError("Cloudflare embeddings API returned an invalid vector index.")
            if index < 0 or index >= len(texts) or ordered[index] is not None:
                raise RuntimeError("Cloudflare embeddings API returned duplicate or invalid indices.")
            if not isinstance(vector, list) or not vector:
                raise RuntimeError("Cloudflare embeddings API returned an empty vector.")
            try:
                values = [float(value) for value in vector]
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Cloudflare embeddings API returned non-numeric values.") from exc
            if len(values) != self.dimensions:
                raise RuntimeError(
                    f"Cloudflare returned {len(values)} dimensions; expected {self.dimensions}. "
                    "Check CLOUDFLARE_EMBEDDING_DIMENSIONS and the selected model."
                )
            if not all(math.isfinite(value) for value in values):
                raise RuntimeError("Cloudflare embeddings API returned non-finite values.")
            ordered[index] = values
        if any(vector is None for vector in ordered):
            raise RuntimeError("Cloudflare embeddings API omitted one or more vectors.")
        return [vector for vector in ordered if vector is not None]

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, (str, bytes)):
            raise ValueError("texts must be a sequence of strings, not a single string.")
        normalized = []
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"text at index {index} must be a non-empty string.")
            normalized.append(text.strip())
        vectors: list[list[float]] = []
        for start in range(0, len(normalized), self.batch_size):
            vectors.extend(self._embed_batch(normalized[start : start + self.batch_size]))
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("query must be a non-empty string.")
        return self._embed([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        cleaned = [text.strip() for text in texts if isinstance(text, str) and text.strip()]
        return self.embed_documents(cleaned) if cleaned else []

    def get_embedding_model(self) -> Embeddings:
        return self
