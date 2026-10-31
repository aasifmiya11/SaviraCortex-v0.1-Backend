from __future__ import annotations
from langchain_core.documents import Document
from qdrant_client import models
from app.rag.vector_stores.qdrant import client as qdrant_client

class DenseRetriever:
    def search(self, query: str, k: int = 20, document_id: str | None = None,
               user_id: str | None = None) -> list[tuple[Document, float]]:
        if not query or not query.strip():
            raise ValueError("query cannot be empty.")
        if k < 1:
            raise ValueError("k must be at least 1.")
        conditions = []
        if document_id is not None:
            conditions.append(models.FieldCondition(
                key="metadata.document_id", match=models.MatchValue(value=str(document_id))))
        if user_id is not None:
            conditions.append(models.FieldCondition(
                key="metadata.user_id", match=models.MatchValue(value=str(user_id))))
        qdrant_filter = models.Filter(must=conditions) if conditions else None
        return qdrant_client.similarity_search_with_score(
            query=query, k=k, query_filter=qdrant_filter)

dense_retriever = DenseRetriever()
