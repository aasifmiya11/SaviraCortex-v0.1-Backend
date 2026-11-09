from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from .qdrant_bm25 import bm25_retriever as default_bm25_retriever
from .dense import dense_retriever as default_dense_retriever
from .fusion import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


class HybridRetrievalPipeline:
    def __init__(
        self,
        bm25_weight: float = 1.0,
        dense_weight: float = 1.0,
        *,
        bm25_retriever=None,
        dense_retriever=None,
    ):
        if bm25_weight < 0 or dense_weight < 0 or bm25_weight + dense_weight == 0:
            raise ValueError("Weights must be non-negative and at least one must be positive.")
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self.bm25_retriever = bm25_retriever or default_bm25_retriever
        self.dense_retriever = dense_retriever or default_dense_retriever

    @staticmethod
    def _rank_trace(items: list[tuple[Document, float]]) -> list[dict[str, Any]]:
        rows = []
        for rank, (document, score) in enumerate(items, 1):
            metadata = document.metadata or {}
            rows.append({
                "rank": rank,
                "document_id": metadata.get("document_id"),
                "document_version_id": metadata.get("document_version_id"),
                "chunk_id": metadata.get("chunk_id") or metadata.get("chunk_index"),
                "page": metadata.get("page"),
                "score": round(float(score), 8),
            })
        return rows

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
        exclude: bool = False,
        excluded_chunk_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query cannot be empty.")
        if organization_id is None or not str(organization_id).strip():
            raise ValueError("organization_id cannot be empty.")
        if top_k < 1 or candidate_k < 1:
            raise ValueError("top_k and candidate_k must be at least 1.")
        if mode not in {"hybrid", "bm25", "dense"}:
            raise ValueError("mode must be hybrid, bm25, or dense.")
        if status is not None and not status.strip():
            raise ValueError("status cannot be empty.")
        if not isinstance(exclude, bool):
            raise ValueError("exclude must be a boolean.")

        logger.info(
            "[RAG][RETRIEVAL_START] mode=%s candidate_k=%d top_k=%d allowed_versions=%d query=%r",
            mode, candidate_k, top_k,
            len(candidate_document_version_ids or []), query[:500],
        )
        bm25: list[tuple[Document, float]] = []
        dense: list[tuple[Document, float]] = []

        try:
            if mode in {"hybrid", "bm25"}:
                bm25 = self.bm25_retriever.search(
                    query=query, organization_id=organization_id, k=candidate_k,
                    document_id=document_id, user_id=user_id, status=status,
                    candidate_document_version_ids=candidate_document_version_ids,
                    exclude=exclude, excluded_chunk_ids=excluded_chunk_ids,
                )
            if mode in {"hybrid", "dense"}:
                dense = self.dense_retriever.search(
                    query=query, organization_id=organization_id, k=candidate_k,
                    document_id=document_id, user_id=user_id, status=status,
                    candidate_document_version_ids=candidate_document_version_ids,
                    exclude=exclude, excluded_chunk_ids=excluded_chunk_ids,
                )
        except Exception:
            logger.exception("[RAG][RETRIEVAL_ERROR] lexical/dense search failed mode=%s", mode)
            raise

        if mode == "bm25":
            ranked = bm25[:top_k]
        elif mode == "dense":
            ranked = dense[:top_k]
        else:
            ranked = reciprocal_rank_fusion(
                [bm25, dense], rrf_k, [self.bm25_weight, self.dense_weight]
            )[:top_k]

        bm25_trace = self._rank_trace(bm25)
        dense_trace = self._rank_trace(dense)
        fused_trace = self._rank_trace(ranked)
        logger.info(
            "[RAG][RANK_TABLES] mode=%s bm25_hits=%d dense_hits=%d fused_hits=%d "
            "BM25=%s DENSE=%s RRF=%s",
            mode, len(bm25), len(dense), len(ranked),
            bm25_trace, dense_trace, fused_trace,
        )

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
            "diagnostics": {"bm25": bm25_trace, "dense": dense_trace, "rrf": fused_trace},
            "context": self.build_context(ranked),
        }

    @staticmethod
    def build_context(ranked: list[tuple[Document, float]]) -> str:
        parts = []
        for index, (document, _) in enumerate(ranked, 1):
            metadata = document.metadata or {}
            source = metadata.get("source_filename") or metadata.get("source") or "Unknown source"
            page = metadata.get("page", "Unknown page")
            parts.append(f"[Source {index}: {source}, page {page}]\n{document.page_content.strip()}")
        return "\n\n---\n\n".join(parts)


retrieval_pipeline = HybridRetrievalPipeline()
