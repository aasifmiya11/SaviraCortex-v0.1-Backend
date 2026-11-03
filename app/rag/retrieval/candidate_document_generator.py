from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agents.Multi_query_generator.schemas import (
    GeneratedQuery,
    QueryVersionScope,
)
from app.rag.vector_stores.qdrant_summary import (
    QdrantSummaryStore,
)

logger = logging.getLogger(__name__)


class CandidateDocument(BaseModel):
    """An authorized document version selected by summary similarity."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_version_id: str
    document_title: str
    document_summary: str
    version_year: int
    version_status: str
    similarity_score: float
    source: str | None = None


class QueryCandidateResult(BaseModel):
    """Candidate documents generated for one contextualized query."""

    model_config = ConfigDict(extra="forbid")

    query: str
    version_scope: QueryVersionScope
    target_versions: list[int] = Field(default_factory=list)
    candidates: list[CandidateDocument] = Field(default_factory=list)

    # Distinguishes a failed search from a successful search with no matches.
    retrieval_error: str | None = None


class CandidateDocumentGenerationError(Exception):
    """Raised when candidate generation cannot complete."""


class CandidateDocumentGenerator:
    """
    Generate authorized document-version candidates for each query.

    Each query performs an independent summary similarity search.
    Searches execute concurrently, while filtering uses the
    PostgreSQL-backed authorized catalogue supplied by the caller.
    """

    def __init__(
        self,
        summary_store: QdrantSummaryStore,
        similarity_threshold: float = 0.40,
        search_limit: int = 20,
        max_concurrency: int = 6,
    ) -> None:
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError(
                "similarity_threshold must be between 0 and 1."
            )

        if isinstance(search_limit, bool) or search_limit < 1:
            raise ValueError("search_limit must be positive.")

        if isinstance(max_concurrency, bool) or max_concurrency < 1:
            raise ValueError("max_concurrency must be positive.")

        self.summary_store = summary_store
        self.similarity_threshold = similarity_threshold
        self.search_limit = search_limit
        self.max_concurrency = max_concurrency

    async def generate_candidates(
        self,
        queries: Sequence[GeneratedQuery],
        authorized_catalogue: list[dict[str, Any]],
        organization_id: UUID | str,
    ) -> list[QueryCandidateResult]:
        """
        Generate candidates independently for every contextualized query.

        Results preserve the input query order and query-to-candidate
        mapping. Duplicate document versions across different queries
        are intentionally retained.
        """

        if not queries:
            raise ValueError("At least one contextualized query is required.")

        organization_id = str(organization_id).strip()
        if not organization_id:
            raise ValueError("organization_id cannot be empty.")

        catalogue_by_version = self._build_catalogue_index(
            authorized_catalogue
        )

        # No authorized versions means there is nothing to retrieve.
        if not catalogue_by_version:
            return [
                self._empty_result(query)
                for query in queries
            ]

        semaphore = asyncio.Semaphore(self.max_concurrency)

        tasks = [
            self._retrieve_for_query(
                query=query,
                catalogue_by_version=catalogue_by_version,
                organization_id=organization_id,
                semaphore=semaphore,
            )
            for query in queries
        ]

        results = await asyncio.gather(*tasks)

        failed_searches = sum(
            result.retrieval_error is not None
            for result in results
        )

        if failed_searches == len(results):
            raise CandidateDocumentGenerationError(
                "Summary search failed for every contextualized query."
            )

        return results

    async def _retrieve_for_query(
        self,
        query: GeneratedQuery,
        catalogue_by_version: dict[str, dict[str, Any]],
        organization_id: str,
        semaphore: asyncio.Semaphore,
    ) -> QueryCandidateResult:
        """Retrieve and filter candidates for one contextualized query."""

        async with semaphore:
            try:
                # QdrantSummaryStore currently uses synchronous QdrantClient.
                # Run its embedding + network operation outside the event loop.
                search_results = await asyncio.to_thread(
                    self.summary_store.search_similar_summaries,
                    query.query,
                    self.search_limit,
                    organization_id=organization_id,
                )

            except Exception:
                logger.exception(
                    "Summary similarity search failed for query: %s",
                    query.query,
                )

                return QueryCandidateResult(
                    query=query.query,
                    version_scope=query.version_scope,
                    target_versions=query.target_versions,
                    retrieval_error="summary_search_failed",
                )

        candidates = self._filter_and_build_candidates(
            search_results=search_results,
            query=query,
            catalogue_by_version=catalogue_by_version,
        )

        return QueryCandidateResult(
            query=query.query,
            version_scope=query.version_scope,
            target_versions=query.target_versions,
            candidates=candidates,
        )

    def _filter_and_build_candidates(
        self,
        search_results: list[dict[str, Any]],
        query: GeneratedQuery,
        catalogue_by_version: dict[str, dict[str, Any]],
    ) -> list[CandidateDocument]:
        """
        Filter Qdrant hits using authoritative catalogue information.

        Qdrant lifecycle status and title/summary are deliberately
        not used as authoritative metadata.
        """

        candidates_by_version: dict[str, CandidateDocument] = {}

        for hit in search_results:
            similarity_score = hit.get("similarity_score")

            if similarity_score is None:
                continue

            similarity_score = float(similarity_score)

            if not math.isfinite(similarity_score):
                continue

            if similarity_score < self.similarity_threshold:
                continue

            version_id = str(
                hit.get("document_version_id") or ""
            ).strip()

            document_id = str(
                hit.get("document_id") or ""
            ).strip()

            if not version_id or not document_id:
                continue

            # This lookup enforces user authorization because the
            # supplied catalogue contains only authorized versions.
            catalogue_entry = catalogue_by_version.get(version_id)

            if catalogue_entry is None:
                continue

            # Check both identifiers to avoid accepting inconsistent hits.
            if document_id != catalogue_entry["document_id"]:
                logger.warning(
                    "Ignoring Qdrant hit with mismatched document ID "
                    "for version %s.",
                    version_id,
                )
                continue

            if not self._matches_version_scope(
                catalogue_entry=catalogue_entry,
                query=query,
            ):
                continue

            candidate_data = {
                "document_id": catalogue_entry["document_id"],
                "document_version_id": version_id,
                "document_title": catalogue_entry["document_title"],
                "document_summary": catalogue_entry["document_summary"],
                "version_year": catalogue_entry["version_year"],
                "version_status": catalogue_entry["version_status"],
                "similarity_score": similarity_score,
            }

            # Source is optional because the current PostgreSQL
            # catalogue does not guarantee that field.
            source = catalogue_entry.get("source")
            if source is not None:
                candidate_data["source"] = source

            candidate = CandidateDocument(**candidate_data)

            # Defensive deduplication within this query only.
            # Cross-query duplicates are intentionally preserved.
            existing = candidates_by_version.get(version_id)

            if (
                existing is None
                or candidate.similarity_score > existing.similarity_score
            ):
                candidates_by_version[version_id] = candidate

        return list(candidates_by_version.values())

    @staticmethod
    def _matches_version_scope(
        catalogue_entry: dict[str, Any],
        query: GeneratedQuery,
    ) -> bool:
        """Apply lifecycle scope and optional target-year filtering."""

        version_status = catalogue_entry["version_status"]

        if (
            query.version_scope == QueryVersionScope.ACTIVE
            and version_status != "active"
        ):
            return False

        if (
            query.version_scope == QueryVersionScope.SUPERSEDED
            and version_status != "superseded"
        ):
            return False

        if (
            query.target_versions
            and catalogue_entry["version_year"] not in query.target_versions
        ):
            return False

        return True

    @staticmethod
    def _build_catalogue_index(
        authorized_catalogue: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """
        Validate and index the authorized catalogue by version ID.

        The catalogue is the authority for version lifecycle and
        candidate metadata.
        """

        if not isinstance(authorized_catalogue, list):
            raise ValueError("authorized_catalogue must be a list.")

        catalogue_by_version: dict[str, dict[str, Any]] = {}

        required_fields = {
            "document_id",
            "document_version_id",
            "document_title",
            "document_summary",
            "version_year",
            "version_status",
        }

        for entry in authorized_catalogue:
            if not isinstance(entry, dict):
                raise ValueError(
                    "Every authorized catalogue entry must be a dictionary."
                )

            if not required_fields.issubset(entry):
                missing = required_fields - entry.keys()
                raise ValueError(
                    f"Catalogue entry is missing fields: {sorted(missing)}"
                )

            document_id = str(entry["document_id"]).strip()
            version_id = str(entry["document_version_id"]).strip()

            if not document_id or not version_id:
                raise ValueError(
                    "Catalogue document IDs cannot be empty."
                )

            if version_id in catalogue_by_version:
                raise ValueError(
                    f"Duplicate document_version_id in catalogue: {version_id}"
                )

            version_status = entry["version_status"]

            if version_status not in {"active", "superseded"}:
                raise ValueError(
                    f"Unsupported catalogue version status: {version_status}"
                )

            version_year = entry["version_year"]

            if (
                isinstance(version_year, bool)
                or not isinstance(version_year, int)
                or version_year < 1
            ):
                raise ValueError(
                    f"Invalid version_year for version {version_id}."
                )

            title = entry["document_title"]
            summary = entry["document_summary"]

            if not isinstance(title, str) or not title.strip():
                raise ValueError(
                    f"Invalid document_title for version {version_id}."
                )

            if not isinstance(summary, str):
                raise ValueError(
                    f"Invalid document_summary for version {version_id}."
                )

            catalogue_by_version[version_id] = {
                "document_id": document_id,
                "document_version_id": version_id,
                "document_title": title,
                "document_summary": summary,
                "version_year": version_year,
                "version_status": version_status,
                **(
                    {"source": entry["source"]}
                    if entry.get("source") is not None
                    else {}
                ),
            }

        return catalogue_by_version

    @staticmethod
    def _empty_result(
        query: GeneratedQuery,
    ) -> QueryCandidateResult:
        """Return an empty successful result when no versions are authorized."""

        return QueryCandidateResult(
            query=query.query,
            version_scope=query.version_scope,
            target_versions=query.target_versions,
            candidates=[],
        )