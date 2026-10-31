from __future__ import annotations
from typing import Any
import sys
from pathlib import Path
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from langchain_core.documents import Document
from .bm25 import bm25_retriever
from .dense import dense_retriever
from .fusion import reciprocal_rank_fusion
from rich import print
class HybridRetrievalPipeline:
    def __init__(self, bm25_weight: float = 1.0, dense_weight: float = 1.0):
        if bm25_weight < 0 or dense_weight < 0 or bm25_weight + dense_weight == 0:
            raise ValueError("Weights must be non-negative and at least one must be positive.")
        self.bm25_weight, self.dense_weight = bm25_weight, dense_weight

    def search(self, query: str, top_k: int = 5, candidate_k: int = 20,
               mode: str = "hybrid", document_id: str | None = None,
               user_id: str | None = None, rrf_k: int = 60) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query cannot be empty.")
        if top_k < 1 or candidate_k < 1:
            raise ValueError("top_k and candidate_k must be at least 1.")
        if mode not in {"hybrid", "bm25", "dense"}:
            raise ValueError("mode must be hybrid, bm25, or dense.")
        bm25, dense = [], []
        if mode in {"hybrid", "bm25"}:
            bm25 = bm25_retriever.search(query, candidate_k, document_id, user_id)
            print(f"=======[BM25 Results {len(bm25)}]=======")
            # print(bm25)
            # print("=============================\n\n\n\n")
        if mode in {"hybrid", "dense"}:
            dense = dense_retriever.search(query, candidate_k, document_id, user_id)
            print(f"=======[Dense Results {len(dense)}]=======")
            # print(dense)
            # print("=============================\n\n\n\n")
        if mode == "bm25": ranked = bm25[:top_k]
        elif mode == "dense": ranked = dense[:top_k]
        else:
            ranked = reciprocal_rank_fusion([bm25, dense], rrf_k,
                [self.bm25_weight, self.dense_weight])[:top_k]
        results = [{"rank": n, "score": float(score),
                    "page_content": doc.page_content,
                    "metadata": dict(doc.metadata or {})}
                   for n, (doc, score) in enumerate(ranked, 1)]
        return {"query": query, "mode": mode, "top_k": top_k,
                "candidate_k": candidate_k, "result_count": len(results),
                "results": results, "context": self.build_context(ranked)}

    @staticmethod
    def build_context(ranked: list[tuple[Document, float]]) -> str:
        parts = []
        for i, (doc, _) in enumerate(ranked, 1):
            md = doc.metadata or {}
            source = md.get("source_filename") or md.get("source") or "Unknown source"
            page = md.get("page", "Unknown page")
            parts.append(f"[Source {i}: {source}, page {page}]\\n{doc.page_content.strip()}")
        return "\\n\\n---\\n\\n".join(parts)

retrieval_pipeline = HybridRetrievalPipeline()

if __name__ == "__main__":
    query = "SajidMiya is a good boy who recieved EdCIL COMPEX schlorship"
    result = retrieval_pipeline.search(query, top_k=3, candidate_k=10, mode="hybrid")
    print(f"=======[Hybrid Retrieval Results {len(result['results'])}]=======")
    print(result)