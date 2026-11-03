
from __future__ import annotations

from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from .qdrant_bm25 import bm25_retriever
from .dense import dense_retriever
from .fusion import reciprocal_rank_fusion


class HybridRetrievalPipeline:
    def __init__(
        self,
        bm25_weight: float = 1.0,
        dense_weight: float = 1.0,
    ):
        if (
            bm25_weight < 0
            or dense_weight < 0
            or bm25_weight + dense_weight == 0
        ):
            raise ValueError(
                "Weights must be non-negative and at least one must be positive."
            )

        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight

    def search(
        self,
        query: str,
        organization_id: UUID | str,
        top_k: int = 10,
        candidate_k: int = 20,
        mode: str = "hybrid",
        document_id: str | None = None,
        user_id: str | None = None,
        rrf_k: int = 60,
        status: str | None = "active",
        candidate_document_version_ids: list[str] | None = None,
    ) -> dict[str, Any]:

        if not query or not query.strip():
            raise ValueError("query cannot be empty.")

        if organization_id is None or not str(organization_id).strip():
            raise ValueError("organization_id cannot be empty.")

        if top_k < 1 or candidate_k < 1:
            raise ValueError(
                "top_k and candidate_k must be at least 1."
            )

        if mode not in {"hybrid", "bm25", "dense"}:
            raise ValueError(
                "mode must be hybrid, bm25, or dense."
            )

        if status is not None and not status.strip():
            raise ValueError("status cannot be empty.")

        bm25 = []
        dense = []

        if mode in {"hybrid", "bm25"}:
            bm25 = bm25_retriever.search(
                query=query,
                organization_id=organization_id,
                k=candidate_k,
                document_id=document_id,
                user_id=user_id,
                status=status,
                candidate_document_version_ids=candidate_document_version_ids,
            )

        if mode in {"hybrid", "dense"}:
            dense = dense_retriever.search(
                query=query,
                organization_id=organization_id,
                k=candidate_k,
                document_id=document_id,
                user_id=user_id,
                status=status,
                candidate_document_version_ids=candidate_document_version_ids,
            )

        if mode == "bm25":
            ranked = bm25[:top_k]

        elif mode == "dense":
            ranked = dense[:top_k]

        else:
            ranked = reciprocal_rank_fusion(
                [bm25, dense],
                rrf_k,
                [self.bm25_weight, self.dense_weight],
            )[:top_k]

        results = [
            {
                "rank": rank,
                "score": float(score),
                "page_content": document.page_content,
                "metadata": dict(document.metadata or {}),
            }
            for rank, (document, score) in enumerate(ranked, 1)
        ]

        return {
            "query": query,
            "mode": mode,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "result_count": len(results),
            "results": results,
            "context": self.build_context(ranked),
        }

    @staticmethod
    def build_context(
        ranked: list[tuple[Document, float]],
    ) -> str:
        parts = []

        for index, (document, _) in enumerate(ranked, 1):
            metadata = document.metadata or {}

            source = (
                metadata.get("source_filename")
                or metadata.get("source")
                or "Unknown source"
            )
            page = metadata.get("page", "Unknown page")

            parts.append(
                f"[Source {index}: {source}, page {page}]\n"
                f"{document.page_content.strip()}"
            )

        return "\n\n---\n\n".join(parts)


retrieval_pipeline = HybridRetrievalPipeline()
