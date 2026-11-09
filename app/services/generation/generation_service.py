from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.v1.generation import (
    ConversationTurnRequest,
    GenerationResponse,
)

logger = logging.getLogger(__name__)


def _escape_markdown_label(value: str) -> str:
    """Keep source titles as literal text inside generated Markdown."""
    special = "\\*_{}[]()#+-.!|>"
    return "".join(
        "\\" + character if character in special else character
        for character in value
    )


def _append_references(markdown: str, citations: list) -> str:
    """Append references only from trusted, validated retrieval metadata."""
    entries: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        evidence_id = citation.evidence_id
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        number = int(evidence_id[1:])
        title = _escape_markdown_label(
            citation.document_title or "Organization document"
        )
        details: list[str] = []
        if citation.page is not None:
            details.append(f"page {citation.page}")
        if citation.section:
            details.append(f"section {_escape_markdown_label(citation.section)}")
        detail_text = ", ".join(details)
        suffix = f" - {detail_text}" if details else ""
        entries.append(f"- **[{number}]** **{title}**{suffix}")
    if not entries:
        return markdown.strip()
    return f"{markdown.rstrip()}\n\n## References\n\n" + "\n".join(entries)


class GenerationServiceError(Exception):
    """Base exception for generation-service failures."""


class GenerationRuntimeUnavailableError(GenerationServiceError):
    """Raised when external generation dependencies cannot be initialized."""


class GenerationExecutionError(GenerationServiceError):
    """Raised when the RAG graph fails during execution."""


class InvalidGenerationQueryError(GenerationServiceError):
    """Raised when workflow input validation rejects the question."""


class GenerationValidationError(GenerationServiceError):
    """Raised when a generated response fails deterministic validation."""


@dataclass(frozen=True, slots=True)
class _SharedRAGComponents:
    """Heavy, process-wide components that do not retain request DB sessions."""

    multi_query_agent: Any
    candidate_document_generator: Any
    hybrid_retrieval_pipeline: Any
    global_fusion: Any
    cross_encoder_reranker: Any
    adaptive_k_selector: Any
    generation_agent: Any
    validator: Any


def _initialize_shared_rag_components() -> _SharedRAGComponents:
    """Initialize heavyweight RAG dependencies once, on first generation use.

    Imports are intentionally local: importing the FastAPI application must not
    download embedding/reranker models or connect to Qdrant.
    """
    try:
        from app.agents.Generation import GenerationAgent
        from app.agents.Multi_query_generator import MultiQueryGeneratorAgent
        from app.rag.retrieval.adaptive_k_selector import AdaptiveKSelector
        from app.rag.retrieval.candidate_document_generator import (
            CandidateDocumentGenerator,
        )
        from app.rag.retrieval.cross_encoder_reranker import CrossEncoderReranker
        from app.rag.retrieval.global_fusion import GlobalResultFusion
        from app.rag.retrieval.pipeline import HybridRetrievalPipeline
        from app.rag.vector_stores.qdrant_summary import summary_store
        from app.validation import StaticValidationLayer

        return _SharedRAGComponents(
            multi_query_agent=MultiQueryGeneratorAgent(),
            candidate_document_generator=CandidateDocumentGenerator(
                summary_store=summary_store,
            ),
            hybrid_retrieval_pipeline=HybridRetrievalPipeline(),
            global_fusion=GlobalResultFusion(),
            cross_encoder_reranker=CrossEncoderReranker(),
            adaptive_k_selector=AdaptiveKSelector(),
            generation_agent=GenerationAgent(),
            validator=StaticValidationLayer(),
        )
    except Exception as exc:
        logger.exception("Unable to initialize shared RAG dependencies.")
        raise GenerationRuntimeUnavailableError(
            "The generation runtime could not be initialized."
        ) from exc


_SHARED_RAG_COMPONENTS: _SharedRAGComponents | None = None
_SHARED_RAG_COMPONENTS_LOCK = threading.Lock()


def _get_shared_rag_components() -> _SharedRAGComponents:
    """Return one process-wide model/vector runtime, initialized exactly once."""
    global _SHARED_RAG_COMPONENTS
    if _SHARED_RAG_COMPONENTS is not None:
        return _SHARED_RAG_COMPONENTS

    with _SHARED_RAG_COMPONENTS_LOCK:
        if _SHARED_RAG_COMPONENTS is None:
            _SHARED_RAG_COMPONENTS = _initialize_shared_rag_components()
        return _SHARED_RAG_COMPONENTS

def _build_graph(
    session: Session,
    shared_components: _SharedRAGComponents | None = None,
    generation_event_callback: Callable[[dict[str, Any]], Any] | None = None,
):
    """Compose a request-scoped graph around shared model/vector dependencies."""
    try:
        from app.repositories.authorization_repository import AuthorizationRepository
        from app.services.authorization.authorization_service import AuthorizationService
        from app.services.retrieval.retrieval_service import RetrievalOrchestrator
        from app.workflows.rag.graph import create_rag_graph

        shared = shared_components or _get_shared_rag_components()
        retriever = RetrievalOrchestrator(
            authorization_service=AuthorizationService(
                AuthorizationRepository(session)
            ),
            multi_query_agent=shared.multi_query_agent,
            candidate_document_generator=shared.candidate_document_generator,
            hybrid_retrieval_pipeline=shared.hybrid_retrieval_pipeline,
            global_fusion=shared.global_fusion,
            cross_encoder_reranker=shared.cross_encoder_reranker,
            adaptive_k_selector=shared.adaptive_k_selector,
        )
        return create_rag_graph(
            retriever=retriever,
            generation_agent=shared.generation_agent,
            validator=shared.validator,
            generation_event_callback=generation_event_callback,
        )
    except GenerationRuntimeUnavailableError:
        raise
    except Exception as exc:
        logger.exception("Unable to compose the request-scoped RAG graph.")
        raise GenerationRuntimeUnavailableError(
            "The generation runtime could not be initialized."
        ) from exc


class GenerationService:
    """Run the existing LangGraph workflow for an authenticated organization member."""

    def __init__(
        self,
        session: Session,
        *,
        graph_factory: Callable[[Session], Any] | None = None,
    ) -> None:
        self.session = session
        self._graph_factory = graph_factory or _build_graph

    async def generate(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_history: list[ConversationTurnRequest] | None = None,
    ) -> GenerationResponse:
        from langchain_core.messages import AIMessage, HumanMessage

        logger.info("[RAG][GENERATION_REQUEST] query=%r organization_id=%s user_id=%s history_turns=%d", query[:500], organization_id, user_id, len(conversation_history or []))
        history = []
        for turn in conversation_history or []:
            if turn.role == "user":
                history.append(HumanMessage(content=turn.content))
            else:
                history.append(AIMessage(content=turn.content))

        try:
            if self._graph_factory is _build_graph:
                # Model loading and Qdrant client initialization can be slow;
                # keep that blocking work off the ASGI event loop.
                shared_components = await asyncio.to_thread(
                    _get_shared_rag_components
                )
                graph = _build_graph(self.session, shared_components)
            else:
                graph = self._graph_factory(self.session)
        except GenerationRuntimeUnavailableError:
            raise
        except Exception as exc:
            logger.exception("Unable to create the generation graph.")
            raise GenerationRuntimeUnavailableError(
                "The generation runtime could not be initialized."
            ) from exc

        try:
            logger.info("[RAG][GENERATION_GRAPH_START] invoking workflow")
            result = await graph.ainvoke(
                {
                    "query": query,
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "context": history,
                }
            )
        except Exception as exc:
            logger.exception(
                "RAG workflow execution failed (organization_id=%s, user_id=%s).",
                organization_id,
                user_id,
            )
            raise GenerationExecutionError(
                "The generation workflow failed."
            ) from exc

        if result.get("is_valid") is not True:
            raise InvalidGenerationQueryError(
                result.get("validation_error")
                or "Please enter a meaningful question."
            )

        answer = result.get("generation_output")
        validation = result.get("validation_result")
        if answer is None or validation is None:
            logger.error("RAG graph ended without a complete validated answer.")
            raise GenerationExecutionError(
                "The generation workflow did not produce a complete answer."
            )

        if validation.is_valid is not True:
            logger.error(
                "RAG answer failed static validation: %s",
                validation.errors,
            )
            raise GenerationValidationError(
                "The generated answer did not pass citation validation."
            )

        retrieved_documents = result.get("retrieved_documents") or []
        logger.info("[RAG][GENERATION_COMPLETE] evidence_count=%d retrieval_attempts=%s citation_count=%d answer_status=%s", len(retrieved_documents), result.get("retrieval_attempt", 0), len(validation.citations), answer.status)
        return GenerationResponse(
            query=result.get("query", query),
            answer=_append_references(answer.segments[0].text, validation.citations),
            status=answer.status,
            citations=validation.citations,
            warnings=validation.warnings,
            missing_information=result.get("missing_information") or [],
            retrieval_attempts=result.get("retrieval_attempt", 0),
            evidence_count=len(retrieved_documents),
        )


    async def generate_stream(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_history: list[ConversationTurnRequest] | None = None,
        on_event: Callable[[dict[str, Any]], Any],
    ) -> GenerationResponse:
        """Run the same validated RAG graph while forwarding provisional text deltas."""
        from langchain_core.messages import AIMessage, HumanMessage

        history = [
            HumanMessage(content=turn.content) if turn.role == "user"
            else AIMessage(content=turn.content)
            for turn in (conversation_history or [])
        ]

        async def emit(event: dict[str, Any]) -> None:
            result = on_event(event)
            if hasattr(result, "__await__"):
                await result

        try:
            if self._graph_factory is _build_graph:
                shared = await asyncio.to_thread(_get_shared_rag_components)
                graph = _build_graph(self.session, shared, generation_event_callback=emit)
            else:
                graph = self._graph_factory(self.session)
            result = await graph.ainvoke({
                "query": query,
                "organization_id": organization_id,
                "user_id": user_id,
                "context": history,
            })
        except (GenerationRuntimeUnavailableError, GenerationExecutionError):
            raise
        except Exception as exc:
            logger.exception(
                "Streaming RAG workflow failed (organization_id=%s, user_id=%s).",
                organization_id, user_id,
            )
            raise GenerationExecutionError("The streaming generation workflow failed.") from exc

        if result.get("is_valid") is not True:
            raise InvalidGenerationQueryError(
                result.get("validation_error") or "Please enter a meaningful question."
            )
        answer = result.get("generation_output")
        validation = result.get("validation_result")
        if answer is None or validation is None:
            raise GenerationExecutionError("The generation workflow did not produce a complete answer.")
        if validation.is_valid is not True:
            raise GenerationValidationError("The generated answer did not pass citation validation.")

        response = GenerationResponse(
            query=result.get("query", query),
            answer=_append_references(answer.segments[0].text, validation.citations),
            status=answer.status,
            citations=validation.citations,
            warnings=validation.warnings,
            missing_information=result.get("missing_information") or [],
            retrieval_attempts=result.get("retrieval_attempt", 0),
            evidence_count=len(result.get("retrieved_documents") or []),
        )
        await emit({"type": "completed", "result": response.model_dump(mode="json")})
        return response
