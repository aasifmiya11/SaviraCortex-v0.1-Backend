from __future__ import annotations

from langchain_core.documents import Document

from ..vector_stores.bm25 import bm25_client


class BM25Retriever:
    def __init__(self):
        self.vector_store = bm25_client

    def search(
        self,
        query: str,
        k: int = 20,
        document_id: str | None = None,
        user_id: str | None = None,
        status: str = "active",
    ) -> list[tuple[Document, float]]:
        if not query or not query.strip():
            raise ValueError("query cannot be empty.")

        if k < 1:
            raise ValueError("k must be at least 1.")

        if not status or not status.strip():
            raise ValueError("status cannot be empty.")

        return self.vector_store.similarity_search_with_score(
            query=query,
            k=k,
            document_id=document_id,
            user_id=user_id,
            status=status,
        )


bm25_retriever = BM25Retriever()