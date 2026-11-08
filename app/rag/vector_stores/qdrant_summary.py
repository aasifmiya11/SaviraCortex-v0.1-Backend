
from __future__ import annotations

from typing import Any
from uuid import UUID

from qdrant_client import QdrantClient, models

from ...core.config import settings
from ..embeddings.jina_embeddings import embedding_client


class QdrantSummaryStore:
    """Qdrant storage dedicated to document-version summaries."""

    def __init__(
        self,
        client: QdrantClient | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.collection_name = (
            collection_name or settings.QDRANT_SUMMARY_COLLECTION_NAME
        )

        if not self.collection_name:
            raise ValueError(
                "QDRANT_SUMMARY_COLLECTION_NAME is not configured."
            )

        self.client = client or QdrantClient(
            url=settings.QDRANT_API_ENDPOINT,
            api_key=settings.QDRANT_API_KEY,
        )

        self._create_collection_if_not_exists()
        self._ensure_payload_indexes()

    def _create_collection_if_not_exists(self) -> None:
        """Create the summary collection using the existing embedding model."""

        if self.client.collection_exists(self.collection_name):
            return

        dimension = len(
            embedding_client.embed_query("document summary dimension check")
        )

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=dimension,
                distance=models.Distance.COSINE,
            ),
        )
        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="organization_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )

    def _ensure_payload_indexes(self) -> None:
        """Ensure fields used by summary-search filters are indexed."""
        collection_info = self.client.get_collection(
            collection_name=self.collection_name
        )
        existing_schema = collection_info.payload_schema or {}

        # delete_document filters on the root-level document_id payload field.
        # Index it on the dedicated summary collection as well as the fields
        # used by summary search; the chunk collection has its own indexes.
        for field_name in (
            "organization_id",
            "document_version_id",
            "document_id",
        ):
            if field_name not in existing_schema:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )

    @staticmethod
    def _normalize_id(value: UUID | str) -> str:
        return str(value)

    def upsert_summary(
        self,
        *,
        document_id: UUID | str,
        document_version_id: UUID | str,
        version_number: int,
        title: str,
        summary: str,
        status: str,
        organization_id: UUID | str,
    ) -> str:
        """
        Insert or replace one document-version summary.

        The document version ID is the Qdrant point ID, making this
        operation idempotent for a given version.
        """

        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string.")

        if version_number < 1:
            raise ValueError("version_number must be at least 1.")

        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string.")

        if not isinstance(status, str) or not status.strip():
            raise ValueError("status must be a non-empty string.")

        document_id = self._normalize_id(document_id)
        version_id = self._normalize_id(document_version_id)
        organization_id = self._normalize_id(organization_id)
        summary = summary.strip()

        vector = embedding_client.embed_query(summary)

        point = models.PointStruct(
            id=version_id,
            vector=vector,
            payload={
                "document_id": document_id,
                "organization_id": organization_id,
                "document_version_id": version_id,
                "version_number": version_number,
                "title": title.strip(),
                "summary": summary,
                "status": status,
            },
        )

        self.client.upsert(
            collection_name=self.collection_name,
            points=[point],
            wait=True,
        )

        return version_id

    def search_similar_summaries(
        self,
        summary: str,
        limit: int = 20,
        *,
        organization_id: UUID | str,
        offset: int = 0,
        document_version_ids: list[UUID | str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search summaries by cosine similarity with paginated Qdrant results.

        All lifecycle statuses are included intentionally. Duplicate
        detection must also find archived and superseded versions.
        """

        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string.")

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        organization_id = self._normalize_id(organization_id)
        if not organization_id.strip():
            raise ValueError("organization_id cannot be empty.")

        must_conditions = [
            models.FieldCondition(
                key="organization_id",
                match=models.MatchValue(value=organization_id),
            )
        ]

        if document_version_ids is not None:
            normalized_version_ids = sorted({
                self._normalize_id(version_id).strip()
                for version_id in document_version_ids
                if self._normalize_id(version_id).strip()
            })
            if not normalized_version_ids:
                return []
            must_conditions.append(
                models.FieldCondition(
                    key="document_version_id",
                    match=models.MatchAny(any=normalized_version_ids),
                )
            )

        vector = embedding_client.embed_query(summary.strip())

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=limit,
            offset=offset,
            query_filter=models.Filter(must=must_conditions),
            with_payload=True,
            with_vectors=False,
        )

        results: list[dict[str, Any]] = []

        for point in response.points:
            payload = point.payload or {}

            similarity_score = float(point.score)
            results.append(
                {
                    "document_id": payload.get("document_id"),
                    "document_version_id": payload.get(
                        "document_version_id", str(point.id)
                    ),
                    "version_number": payload.get("version_number"),
                    "title": payload.get("title"),
                    "summary": payload.get("summary"),
                    "status": payload.get("status"),
                    "score": similarity_score,
                    "similarity_score": similarity_score,
                }
            )

        return results

    def delete_summary(self, document_version_id: UUID | str) -> None:
        """Delete one version's summary point."""

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(
                points=[self._normalize_id(document_version_id)]
            ),
            wait=True,
        )

    def delete_document(self, document_id: UUID | str) -> None:
        """Delete every version summary belonging to a logical document."""
        normalized_document_id = self._normalize_id(document_id)
        if not normalized_document_id.strip():
            raise ValueError("document_id cannot be empty.")
        if not self.client.collection_exists(self.collection_name):
            return

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=normalized_document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def delete_collection(self) -> None:
        """Delete the dedicated summary collection."""

        self.client.delete_collection(self.collection_name)


# Shared instance for application use.
summary_store = QdrantSummaryStore()
