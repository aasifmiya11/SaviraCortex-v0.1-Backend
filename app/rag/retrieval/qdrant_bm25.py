from __future__ import annotations

from uuid import UUID

from langchain_core.documents import Document

from ..vector_stores.qdrant import client as qdrant_client


class QdrantBM25Retriever:
    def __init__(self, vector_store=None):
        self.vector_store = vector_store or qdrant_client

    def search(
        self,
        query: str,
        organization_id: UUID | str,
        k: int = 20,
        document_id: str | None = None,
        user_id: str | None = None,
        status: str | None = "active",
    ) -> list[tuple[Document, float]]:
        if not query or not query.strip():
            raise ValueError("query cannot be empty.")

        if organization_id is None or not str(organization_id).strip():
            raise ValueError("organization_id cannot be empty.")

        if k < 1:
            raise ValueError("k must be at least 1.")

        if status is not None and not status.strip():
            raise ValueError("status cannot be empty.")

        return self.vector_store.bm25_search_with_score(
            query=query,
            k=k,
            query_filter=self._build_filter(
                organization_id=organization_id,
                document_id=document_id,
                user_id=user_id,
                status=status,
            ),
        )

    @staticmethod
    def _build_filter(
        *,
        organization_id: UUID | str,
        document_id: str | None,
        user_id: str | None,
        status: str | None,
    ):
        from qdrant_client import models

        conditions = []
        conditions.append(
            models.FieldCondition(
                key="metadata.organization_id",
                match=models.MatchValue(value=str(organization_id)),
            )
        )
        if document_id is not None:
            conditions.append(
                models.FieldCondition(
                    key="metadata.document_id",
                    match=models.MatchValue(value=str(document_id)),
                )
            )
        if user_id is not None:
            conditions.append(
                models.FieldCondition(
                    key="metadata.user_id",
                    match=models.MatchValue(value=str(user_id)),
                )
            )
        if status is not None:
            conditions.append(
                models.FieldCondition(
                    key="metadata.status",
                    match=models.MatchValue(value=status),
                )
            )

        return models.Filter(must=conditions) if conditions else None


bm25_retriever = QdrantBM25Retriever()
