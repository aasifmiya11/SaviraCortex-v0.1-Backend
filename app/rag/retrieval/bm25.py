
from __future__ import annotations

from langchain_core.documents import Document

from ..vector_stores.bm25 import bm25_client


class BM25Retriever:
    """Retrieval interface for the persistent BM25 vector store."""

    def __init__(self):
        self.vector_store = bm25_client

    def search(
        self,
        query: str,
        k: int = 20,
        document_id: str | None = None,
        user_id: str | None = None,
    ) -> list[tuple[Document, float]]:

        if not query or not query.strip():
            raise ValueError("query cannot be empty.")

        if k < 1:
            raise ValueError("k must be at least 1.")

        return self.vector_store.similarity_search_with_score(
            query=query,
            k=k,
            document_id=document_id,
            user_id=user_id,
        )


# Singleton instance
bm25_retriever = BM25Retriever()
