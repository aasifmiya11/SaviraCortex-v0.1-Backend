from __future__ import annotations

from uuid import UUID

from langchain_core.documents import Document
from qdrant_client import models

from .chunk_exclusion import build_excluded_chunk_filters
from ..vector_stores.qdrant import client as qdrant_client


class DenseRetriever:

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
        candidate_document_version_ids: list[str] | None = None,
        exclude: bool = False,
        excluded_chunk_ids: list[str] | None = None,
    ) -> list[tuple[Document, float]]:

        if not query or not query.strip():
            raise ValueError("query cannot be empty.")

        if organization_id is None or not str(organization_id).strip():
            raise ValueError("organization_id cannot be empty.")

        if k < 1:
            raise ValueError("k must be at least 1.")

        if status is not None and not status.strip():
            raise ValueError("status cannot be empty.")

        if not isinstance(exclude, bool):
            raise ValueError("exclude must be a boolean.")

        if candidate_document_version_ids is not None:
            candidate_document_version_ids = list(
                dict.fromkeys(
                    str(version_id).strip()
                    for version_id in candidate_document_version_ids
                    if version_id and str(version_id).strip()
                )
            )
            if not candidate_document_version_ids:
                return []

        conditions = [
            models.FieldCondition(
                key="metadata.organization_id",
                match=models.MatchValue(value=str(organization_id)),
            )
        ]

        # Filter by logical document ID.
        if document_id is not None:
            conditions.append(
                models.FieldCondition(
                    key="metadata.document_id",
                    match=models.MatchValue(value=str(document_id)),
                )
            )

        # Filter by user ID.
        if user_id is not None:
            conditions.append(
                models.FieldCondition(
                    key="metadata.user_id",
                    match=models.MatchValue(value=str(user_id)),
                )
            )

        if candidate_document_version_ids is not None:
            conditions.append(
                models.FieldCondition(
                    key="metadata.document_version_id",
                    match=models.MatchAny(any=candidate_document_version_ids),
                )
            )

        # Lifecycle filtering.
        if status is not None:
            conditions.append(
                models.FieldCondition(
                    key="metadata.status",
                    match=models.MatchValue(value=status),
                )
            )

        excluded_filters = (
            build_excluded_chunk_filters(excluded_chunk_ids)
            if exclude
            else []
        )

        qdrant_filter = (
            models.Filter(must=conditions, must_not=excluded_filters)
            if conditions or excluded_filters
            else None
        )

        return self.vector_store.similarity_search_with_score(
            query=query,
            k=k,
            query_filter=qdrant_filter,
        )


dense_retriever = DenseRetriever()
