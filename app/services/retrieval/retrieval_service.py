from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from langchain_core.messages import BaseMessage

from app.agents.Multi_query_generator.agent import MultiQueryGeneratorAgent
from app.agents.Multi_query_generator.schemas import (
    AvailableDocument,
    AvailableDocuments,
    GeneratedQuery,
)
from app.rag.retrieval.adaptive_k_selector import AdaptiveKSelector
from app.rag.retrieval.candidate_document_generator import (
    CandidateDocumentGenerationError,
    CandidateDocumentGenerator,
    QueryCandidateResult,
)
from app.rag.retrieval.cross_encoder_reranker import CrossEncoderReranker
from app.rag.retrieval.global_fusion import GlobalResultFusion
from app.rag.retrieval.pipeline import HybridRetrievalPipeline
from app.services.authorization.authorization_service import AuthorizationService

logger = logging.getLogger(__name__)


class RetrievalOrchestrationError(Exception):
    """Raised when retrieval orchestration cannot produce a valid result."""


class RetrievalOrchestrator:
    """Coordinate authorization, query generation, retrieval, fusion and reranking.

    The orchestrator owns no database session and does not initialize heavyweight
    models. All dependencies are injected so the application can control their
    lifecycle and tests can replace them with fakes.

    AuthorizationService currently uses a synchronous SQLAlchemy repository.
    Its method is called on the caller's event-loop thread to avoid moving a
    request-scoped SQLAlchemy Session across threads. If the database call
    becomes a latency bottleneck, expose an async authorization boundary or
    create/use the Session inside a dedicated worker instead of sharing it.
    """

    def __init__(
        self,
        *,
        authorization_service: AuthorizationService,
        multi_query_agent: MultiQueryGeneratorAgent,
        candidate_document_generator: CandidateDocumentGenerator,
        hybrid_retrieval_pipeline: HybridRetrievalPipeline,
        global_fusion: GlobalResultFusion,
        cross_encoder_reranker: CrossEncoderReranker,
        adaptive_k_selector: AdaptiveKSelector,
        retrieval_concurrency: int = 6,
    ) -> None:
        if (
            isinstance(retrieval_concurrency, bool)
            or not isinstance(retrieval_concurrency, int)
            or retrieval_concurrency < 1
        ):
            raise ValueError("retrieval_concurrency must be a positive integer.")

        self.authorization_service = authorization_service
        self.multi_query_agent = multi_query_agent
        self.candidate_document_generator = candidate_document_generator
        self.hybrid_retrieval_pipeline = hybrid_retrieval_pipeline
        self.global_fusion = global_fusion
        self.cross_encoder_reranker = cross_encoder_reranker
        self.adaptive_k_selector = adaptive_k_selector
        self.retrieval_concurrency = retrieval_concurrency

    async def retrieve(
        self,
        *,
        current_query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_history: Sequence[BaseMessage] | None = None,
        top_k: int = 10,
        candidate_k: int = 20,
        mode: str = "hybrid",
        rrf_k: int = 60,
        exclude: bool = False,
        excluded_chunk_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run retrieval and return selected chunks with provenance/statistics."""

        if not isinstance(exclude, bool):
            raise ValueError("exclude must be a boolean.")
        if excluded_chunk_ids is not None and not isinstance(excluded_chunk_ids, list):
            raise ValueError("excluded_chunk_ids must be a list of strings or None.")

        self._validate_request(
            current_query=current_query,
            organization_id=organization_id,
            user_id=user_id,
            top_k=top_k,
            candidate_k=candidate_k,
            mode=mode,
            rrf_k=rrf_k,
        )

        history = list(conversation_history or [])

        # This service method uses a synchronous request-scoped SQLAlchemy
        # Session. Keep the call on the same thread that owns that Session.
        logger.info("[RAG][REQUEST_START] query=%r mode=%s top_k=%d candidate_k=%d", current_query[:500], mode, top_k, candidate_k)
        authorized_catalogue = self.authorization_service.get_authorized_document_catalog(
            organization_id=organization_id,
            user_id=user_id,
        )
        logger.info("[RAG][AUTHORIZATION] authorized_document_versions=%d", len(authorized_catalogue))

        if not authorized_catalogue:
            return self._empty_response(
                current_query=current_query,
                top_k=top_k,
                candidate_k=candidate_k,
                mode=mode,
                reason="no_authorized_document_versions",
            )

        available_documents = self._build_available_documents(authorized_catalogue)

        generated_queries = await self.multi_query_agent.agenerate(
            current_query=current_query,
            conversation_history=history,
            available_documents=available_documents,
        )
        generated_queries = self._deduplicate_queries(generated_queries, set())
        logger.info("[RAG][MULTI_QUERY] generated=%d queries=%s", len(generated_queries), [self._query_to_dict(q) for q in generated_queries])
        if not generated_queries:
            raise RetrievalOrchestrationError(
                "The multi-query generator returned no usable queries."
            )

        all_queries: list[GeneratedQuery] = list(generated_queries)
        branch_results: list[dict[str, Any]] = []
        branch_stats: list[dict[str, Any]] = []
        expansion_round = 0
        expansion_stop_reason = "target_met"
        candidate_generation_error = None

        try:
            candidate_results = await self.candidate_document_generator.generate_candidates(
                queries=generated_queries,
                authorized_catalogue=authorized_catalogue,
                organization_id=organization_id,
            )
        except CandidateDocumentGenerationError as exc:
            logger.exception("Initial candidate generation failed.")
            response = self._empty_response(
                current_query=current_query,
                top_k=top_k,
                candidate_k=candidate_k,
                mode=mode,
                reason="candidate_generation_failed",
            )
            response["candidate_generation_error"] = str(exc)
            response["generated_queries"] = [
                self._query_to_dict(query) for query in all_queries
            ]
            response["expansion"]["max_rounds"] = (
                self.adaptive_k_selector.max_expansion_rounds
            )
            response["expansion"]["score_threshold"] = (
                self.adaptive_k_selector.score_threshold
            )
            response["expansion"]["stop_reason"] = "candidate_generation_failed"
            return response

        new_branches, new_stats = await self._retrieve_candidate_branches(
            candidate_results=candidate_results,
            organization_id=organization_id,
            top_k=candidate_k,
            candidate_k=candidate_k,
            mode=mode,
            rrf_k=rrf_k,
            exclude=exclude,
            excluded_chunk_ids=excluded_chunk_ids,
        )
        branch_results.extend(new_branches)
        branch_stats.extend(new_stats)

        fused, reranked, selection = await self._fuse_rerank_select(
            current_query=current_query,
            branch_results=branch_results,
            top_k=top_k,
            rrf_k=rrf_k,
            expansion_round=expansion_round,
        )

        # Single-pass mode stops immediately after the first Adaptive-K selection.
        # A low selected count is diagnostic only and never triggers another query.
        expansion_stop_reason = "disabled_single_pass"
        candidate_generation_error = None

        return {
            "query": current_query,
            "mode": mode,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "selected_candidates": selection["selected_candidates"],
            "selected_count": selection["selected_count"],
            "eligible_count": selection["eligible_count"],
            "fused_count": len(fused),
            "reranked_count": len(reranked),
            "generated_queries": [self._query_to_dict(query) for query in all_queries],
            "branch_count": len(branch_results),
            "branches": branch_stats,
            "expansion": {
                "rounds_performed": 0,
                "max_rounds": selection["max_expansion_rounds"],
                "required_after_final_round": False,
                "stop_reason": expansion_stop_reason,
                "score_threshold": selection["score_threshold"],
            },
            "retrieval_reason": None,
            "candidate_generation_error": candidate_generation_error,
        }

    async def _retrieve_candidate_branches(
        self,
        *,
        candidate_results: Sequence[QueryCandidateResult],
        organization_id: UUID,
        top_k: int,
        candidate_k: int,
        mode: str,
        rrf_k: int,
        exclude: bool = False,
        excluded_chunk_ids: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        semaphore = asyncio.Semaphore(self.retrieval_concurrency)

        async def retrieve_one(
            candidate_result: QueryCandidateResult,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            version_ids = [
                candidate.document_version_id
                for candidate in candidate_result.candidates
            ]
            stats = {
                "query": candidate_result.query,
                "candidate_version_count": len(version_ids),
                "candidate_document_version_ids": version_ids,
                "result_count": 0,
                "retrieval_error": candidate_result.retrieval_error,
            }

            if candidate_result.retrieval_error or not version_ids:
                return (
                    {"query": candidate_result.query, "results": []},
                    stats,
                )

            async with semaphore:
                result = await asyncio.to_thread(
                    self.hybrid_retrieval_pipeline.search,
                    query=candidate_result.query,
                    organization_id=organization_id,
                    top_k=top_k,
                    candidate_k=candidate_k,
                    mode=mode,
                    rrf_k=rrf_k,
                    # Candidate versions have already been authorized and
                    # lifecycle-filtered. Include superseded versions too.
                    status=None,
                    candidate_document_version_ids=version_ids,
                    exclude=exclude,
                    excluded_chunk_ids=excluded_chunk_ids,
                )

            branch = {
                "query": candidate_result.query,
                "results": result["results"],
            }
            stats["result_count"] = result["result_count"]
            stats["rank_diagnostics"] = result.get("diagnostics", {})
            logger.info("[RAG][QUERY_BRANCH] query=%r candidate_versions=%s results=%d rank_tables=%s", candidate_result.query[:300], version_ids, result["result_count"], result.get("diagnostics", {}))
            return branch, stats

        pairs = await asyncio.gather(
            *(retrieve_one(item) for item in candidate_results)
        )
        return [pair[0] for pair in pairs], [pair[1] for pair in pairs]

    async def _fuse_rerank_select(
        self,
        *,
        current_query: str,
        branch_results: list[dict[str, Any]],
        top_k: int,
        rrf_k: int,
        expansion_round: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        # Keep enough fused candidates for reranking. Each branch contributes
        # up to candidate_k results; the global fusion component applies its
        # own deterministic deduplication and ranking.
        fusion_top_k = max(top_k, sum(len(branch["results"]) for branch in branch_results))
        fused = self.global_fusion.fuse(
            branch_results=branch_results,
            top_k=max(1, fusion_top_k),
            rrf_k=rrf_k,
        )

        logger.info("[RAG][GLOBAL_FUSION_COMPLETE] branch_count=%d fused_count=%d global_table=%s", len(branch_results), len(fused), [{"rank": x.get("global_rank"), "document_id": (x.get("metadata") or {}).get("document_id"), "document_version_id": (x.get("metadata") or {}).get("document_version_id"), "chunk_id": x.get("chunk_id"), "rrf_score": x.get("global_rrf_score"), "query_ranks": x.get("provenance", [])} for x in fused])
        reranked = await asyncio.to_thread(
            self.cross_encoder_reranker.rerank,
            current_query,
            fused,
        ) if fused else []
        logger.info("[RAG][CROSS_ENCODER_RERANK] candidates=%d reranked_table=%s", len(fused), [{"rerank_rank": i, "document_id": (x.get("metadata") or {}).get("document_id"), "document_version_id": (x.get("metadata") or {}).get("document_version_id"), "chunk_id": x.get("chunk_id"), "global_rank": x.get("global_rank"), "reranker_score": x.get("reranker_score")} for i, x in enumerate(reranked, 1)])

        selection = self.adaptive_k_selector.select(
            reranked,
            expansion_round=expansion_round,
        )
        logger.info("[RAG][ADAPTIVE_SELECTION] expansion_round=%d eligible=%s selected=%s expansion_required=%s selected_table=%s", expansion_round, selection.get("eligible_count"), selection.get("selected_count"), selection.get("expansion_required"), selection.get("selected_candidates", []))
        return fused, reranked, selection

    @staticmethod
    def _build_available_documents(
        authorized_catalogue: list[dict[str, Any]],
    ) -> AvailableDocuments:
        active: list[AvailableDocument] = []
        superseded: list[AvailableDocument] = []

        for entry in authorized_catalogue:
            item = AvailableDocument(
                document_title=entry["document_title"],
                document_summary=entry["document_summary"],
                version_year=entry["version_year"],
                version_status=entry["version_status"],
            )
            if item.version_status == "active":
                active.append(item)
            elif item.version_status == "superseded":
                superseded.append(item)
            else:
                raise ValueError(
                    f"Unsupported authorized version status: {item.version_status}"
                )

        return AvailableDocuments(
            active_documents=active,
            superseded_documents=superseded,
        )

    @staticmethod
    def _deduplicate_queries(
        queries: Sequence[GeneratedQuery],
        existing: set[str],
    ) -> list[GeneratedQuery]:
        unique: list[GeneratedQuery] = []
        seen = set(existing)
        for query in queries:
            normalized = query.query.strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(query)
        return unique

    @staticmethod
    def _query_to_dict(query: GeneratedQuery) -> dict[str, Any]:
        return {
            "query": query.query,
            "version_scope": query.version_scope.value,
            "target_versions": list(query.target_versions),
        }

    @staticmethod
    def _validate_request(
        *,
        current_query: str,
        organization_id: UUID,
        user_id: UUID,
        top_k: int,
        candidate_k: int,
        mode: str,
        rrf_k: int,
    ) -> None:
        if not isinstance(current_query, str) or not current_query.strip():
            raise ValueError("current_query cannot be empty.")
        if not isinstance(organization_id, UUID):
            raise ValueError("organization_id must be a UUID.")
        if not isinstance(user_id, UUID):
            raise ValueError("user_id must be a UUID.")
        for name, value in (("top_k", top_k), ("candidate_k", candidate_k), ("rrf_k", rrf_k)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if mode not in {"hybrid", "bm25", "dense"}:
            raise ValueError("mode must be hybrid, bm25, or dense.")

    @staticmethod
    def _empty_response(
        *,
        current_query: str,
        top_k: int,
        candidate_k: int,
        mode: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "query": current_query,
            "mode": mode,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "selected_candidates": [],
            "selected_count": 0,
            "eligible_count": 0,
            "fused_count": 0,
            "reranked_count": 0,
            "generated_queries": [],
            "branch_count": 0,
            "branches": [],
            "expansion": {
                "rounds_performed": 0,
                "max_rounds": 0,
                "required_after_final_round": False,
                "stop_reason": reason,
                "score_threshold": None,
            },
            "retrieval_reason": reason,
            "candidate_generation_error": None,
        }
