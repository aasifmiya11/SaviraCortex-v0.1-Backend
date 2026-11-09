from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.checkpointer import conversation_thread_lock, get_checkpointer, get_store
from app.models import Conversation
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.v1.generation import GenerationResponse
from app.services.generation.generation_service import (
    GenerationExecutionError,
    GenerationRuntimeUnavailableError,
    GenerationService,
    GenerationValidationError,
    InvalidGenerationQueryError,
    _append_references,
    _build_graph,
    _get_shared_rag_components,
)

logger = logging.getLogger(__name__)


class PersistentGenerationService(GenerationService):
    """Run RAG against a backend-owned conversation and persisted LangGraph thread."""

    def __init__(
        self,
        session: Session,
        *,
        checkpointer: Any | None = None,
        store: Any | None = None,
        graph_factory: Callable[[Session], Any] | None = None,
    ) -> None:
        super().__init__(session, graph_factory=graph_factory)
        self.checkpointer = checkpointer if checkpointer is not None else get_checkpointer()
        self.store = store if store is not None else get_store()
        self.conversations = ConversationRepository(session)
        self.last_conversation_id: UUID | None = None

    def _prepare_conversation(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID | None,
        request_id: UUID,
    ) -> Conversation:
        if conversation_id is None:
            conversation = self.conversations.find_by_initial_request(
                organization_id=organization_id,
                user_id=user_id,
                request_id=request_id,
            )
            if conversation is None:
                conversation = self.conversations.create_with_user_message(
                    organization_id=organization_id,
                    user_id=user_id,
                    request_id=request_id,
                    content=query,
                )
        else:
            conversation = self.conversations.get_owned(
                conversation_id, organization_id, user_id
            )
        self.last_conversation_id = conversation.id
        return conversation

    async def _create_graph(
        self,
        *,
        on_event: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        if self._graph_factory is _build_graph:
            if self.checkpointer is None:
                raise GenerationRuntimeUnavailableError(
                    "The PostgreSQL conversation checkpointer is not initialized."
                )
            if self.store is None:
                raise GenerationRuntimeUnavailableError(
                    "The PostgreSQL cross-thread memory Store is not initialized."
                )
            shared = await asyncio.to_thread(_get_shared_rag_components)

            async def emit(event: dict[str, Any]) -> None:
                if on_event is None:
                    return
                result = on_event(event)
                if hasattr(result, "__await__"):
                    await result

            return _build_graph(
                self.session,
                shared,
                generation_event_callback=emit if on_event is not None else None,
                checkpointer=self.checkpointer,
                store=self.store,
            )
        return self._graph_factory(self.session)

    @staticmethod
    def _config(conversation_id: UUID) -> dict[str, Any]:
        return {"configurable": {"thread_id": str(conversation_id)}}

    async def _remember_user_message(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
    ) -> None:
        if self.store is None:
            return
        from app.memory.cross_thread_memory import CrossThreadMemoryService

        await CrossThreadMemoryService(self.store).remember_user_message(
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            user_message=query,
        )
    async def _persist_assistant_turn(
        self,
        *,
        graph: Any,
        config: dict[str, Any],
        conversation: Conversation,
        request_id: UUID,
        response: GenerationResponse,
    ) -> None:
        if self.checkpointer is not None and hasattr(graph, "aupdate_state"):
            await graph.aupdate_state(
                config,
                {
                    "messages": [
                        AIMessage(
                            id=f"assistant:{request_id}",
                            content=response.answer,
                        )
                    ]
                },
            )
        self.conversations.append_assistant_message(
            conversation=conversation,
            request_id=request_id,
            content=response.answer,
            metadata=response.model_dump(mode="json"),
        )

    def _validated_response(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
        result: dict[str, Any],
    ) -> GenerationResponse:
        if result.get("is_valid") is not True:
            raise InvalidGenerationQueryError(
                result.get("validation_error") or "Please enter a meaningful question."
            )

        answer = result.get("generation_output")
        validation = result.get("validation_result")
        if answer is None or validation is None:
            raise GenerationExecutionError(
                "The generation workflow did not produce a complete answer."
            )
        if validation.is_valid is not True:
            raise GenerationValidationError(
                "The generated answer did not pass citation validation."
            )

        answer_markdown = _append_references(
            answer.segments[0].text, validation.citations
        )
        generation_id = self._persist_generation_record(
            query=result.get("query", query),
            organization_id=organization_id,
            user_id=user_id,
            result=result,
            answer_markdown=answer_markdown,
            answer_status=answer.status,
        )
        return GenerationResponse(
            generation_id=generation_id,
            conversation_id=conversation_id,
            request_id=request_id,
            query=result.get("query", query),
            answer=answer_markdown,
            status=answer.status,
            citations=validation.citations,
            warnings=validation.warnings,
            missing_information=result.get("missing_information") or [],
            retrieval_attempts=result.get("retrieval_attempt", 0),
            evidence_count=len(result.get("retrieved_documents") or []),
        )

    async def generate(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID | None = None,
        request_id: UUID | None = None,
    ) -> GenerationResponse:
        request_id = request_id or uuid4()
        conversation = self._prepare_conversation(
            query=query,
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
        )
        async with conversation_thread_lock(conversation.id):
            self.conversations.append_user_message(
                conversation=conversation,
                request_id=request_id,
                content=query,
            )
            existing = self.conversations.get_assistant_response(
                conversation.id, request_id
            )
            if existing:
                response = GenerationResponse.model_validate(existing)
                await self._remember_user_message(
                    query=query,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation.id,
                    request_id=request_id,
                )
                return response

            config = self._config(conversation.id)
            graph = await self._create_graph()
            graph_input = {
                "query": query,
                "organization_id": organization_id,
                "user_id": user_id,
                "request_id": str(request_id),
                "messages": [HumanMessage(id=str(request_id), content=query)],
            }
            try:
                result = await graph.ainvoke(
                    graph_input,
                    config=config if self.checkpointer is not None else None,
                )
            except Exception as exc:
                logger.exception(
                    "Persistent RAG execution failed (conversation_id=%s).",
                    conversation.id,
                )
                raise GenerationExecutionError("The generation workflow failed.") from exc

            response = self._validated_response(
                query=query,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation.id,
                request_id=request_id,
                result=result,
            )
            await self._persist_assistant_turn(
                graph=graph,
                config=config,
                conversation=conversation,
                request_id=request_id,
                response=response,
            )
            await self._remember_user_message(
                query=query,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation.id,
                request_id=request_id,
            )
            return response

    async def generate_stream(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID | None = None,
        request_id: UUID | None = None,
        on_event: Callable[[dict[str, Any]], Any],
    ) -> GenerationResponse:
        request_id = request_id or uuid4()
        conversation = self._prepare_conversation(
            query=query,
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
        )

        async def emit(event: dict[str, Any]) -> None:
            result = on_event(event)
            if hasattr(result, "__await__"):
                await result

        async with conversation_thread_lock(conversation.id):
            self.conversations.append_user_message(
                conversation=conversation,
                request_id=request_id,
                content=query,
            )
            existing = self.conversations.get_assistant_response(
                conversation.id, request_id
            )
            if existing:
                response = GenerationResponse.model_validate(existing)
                await emit({"type": "completed", "result": response.model_dump(mode="json")})
                await self._remember_user_message(
                    query=query,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation.id,
                    request_id=request_id,
                )
                return response

            config = self._config(conversation.id)
            graph = await self._create_graph(on_event=emit)
            graph_input = {
                "query": query,
                "organization_id": organization_id,
                "user_id": user_id,
                "request_id": str(request_id),
                "messages": [HumanMessage(id=str(request_id), content=query)],
            }
            try:
                result = await graph.ainvoke(
                    graph_input,
                    config=config if self.checkpointer is not None else None,
                )
            except Exception as exc:
                logger.exception(
                    "Persistent streaming RAG failed (conversation_id=%s).",
                    conversation.id,
                )
                raise GenerationExecutionError(
                    "The streaming generation workflow failed."
                ) from exc

            response = self._validated_response(
                query=query,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation.id,
                request_id=request_id,
                result=result,
            )
            await self._persist_assistant_turn(
                graph=graph,
                config=config,
                conversation=conversation,
                request_id=request_id,
                response=response,
            )
            await emit({"type": "completed", "result": response.model_dump(mode="json")})
            await self._remember_user_message(
                query=query,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation.id,
                request_id=request_id,
            )
            return response


async def generate_conversation_title(
    *,
    conversation_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    first_message: str,
) -> None:
    """Generate a concise title without delaying the main RAG response."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.core.database import SessionLocal
        from app.llm.generator_client import generator_llm_client

        llm = generator_llm_client.get_llm(temperature=0, max_output_tokens=32)
        title_result = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Create a concise conversation title from the first user "
                        "message. Return only a descriptive title of 5 to 8 words. "
                        "Do not use quotation marks or end punctuation."
                    )
                ),
                HumanMessage(content=first_message[:2000]),
            ]
        )
        title = " ".join(str(title_result.content).strip().strip('"\'').split())
        title = title[:255].strip()
        if not title:
            return

        session = SessionLocal()
        try:
            session.execute(
                update(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.organization_id == organization_id,
                    Conversation.user_id == user_id,
                    Conversation.title_is_user_edited.is_(False),
                    Conversation.title_generated.is_(False),
                )
                .values(
                    title=title,
                    title_generated=True,
                    updated_at=func.now(),
                )
            )
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.exception(
            "Conversation title generation failed (conversation_id=%s); fallback title retained.",
            conversation_id,
        )
