from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.Generation.schemas import GenerationStatus
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.checkpointer import conversation_thread_lock, get_checkpointer, get_store
from app.models import Conversation, ConversationPath, Organization, GuardrailAuditEvent
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.v1.generation import GenerationResponse
from app.guardrails.pii_detector import detect_pii, redact_pii
from app.guardrails.runtime_schemas import default_guardrail_policy, resolve_effective_policy
from app.guardrails.runtime_service import (
    GuardrailBlockedError,
    GuardrailConsentRequiredError,
    RuntimeGuardrailService,
)
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

from app.services.generation.image_attachments import prepare_image_attachments

logger = logging.getLogger(__name__)


def _vision_compatibility_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in (
        "image_url", "image input", "vision", "multimodal", "unsupported image",
        "does not support image", "image content",
    ))


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

    def _persist_guardrail_audit(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        request_id: UUID,
        stage: str,
        decision: str,
        findings: list[dict[str, Any]],
        policy,
    ) -> None:
        """Persist categories/actions only; never persist raw request or response text."""
        if not all(hasattr(self.session, method) for method in ("add", "commit", "rollback")):
            return
        categories = sorted({str(item.get("category", "unknown")) for item in findings})
        actions = policy.input_actions if stage.startswith("input") else policy.output_actions
        details = {
            "finding_count": len(findings),
            "actions": {
                category: (
                    "consent_flow" if category == "pii" else
                    "topicality_route" if category == "topicality" else
                    getattr(actions.get(category), "value", actions.get(category, "block"))
                )
                for category in categories
            },
            "confidence": {
                str(item.get("category")): round(float(item.get("confidence", 1.0)), 4)
                for item in findings
            },
        }
        try:
            self.session.add(GuardrailAuditEvent(
                organization_id=organization_id,
                user_id=user_id,
                request_id=request_id,
                stage=stage,
                decision=decision,
                categories=categories,
                details=details,
            ))
            self.session.commit()
        except Exception:
            self.session.rollback()
            logger.exception(
                "Unable to persist guardrail audit event (request_id=%s, stage=%s).",
                request_id,
                stage,
            )

    def _existing_idempotent_response(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID | None,
        request_id: UUID,
    ) -> GenerationResponse | None:
        # Return an already validated result before running PII preflight again.
        # This keeps retries idempotent without resending the original input.
        if not hasattr(self.session, "get"):
            return None
        if conversation_id is None:
            conversation = self.conversations.find_by_initial_request(
                organization_id=organization_id,
                user_id=user_id,
                request_id=request_id,
            )
        else:
            conversation = self.conversations.get_owned(
                conversation_id, organization_id, user_id
            )
        if conversation is None:
            return None
        saved = self.conversations.get_assistant_response(conversation.id, request_id)
        return GenerationResponse.model_validate(saved) if saved else None

    def _effective_guardrail_policy(self, organization_id: UUID):
        # Lightweight fake sessions are used by graph unit tests; production requests
        # always receive a SQLAlchemy session and resolve the tenant's stored policy.
        if not hasattr(self.session, "get"):
            return default_guardrail_policy()
        organization = self.session.get(Organization, organization_id)
        if organization is None:
            raise ValueError("Organization not found.")
        return resolve_effective_policy(organization.guardrail_policy or {})

    async def _prepare_guarded_query(self, *, query: str, policy, pii_action: str | None) -> str:
        pii = await asyncio.to_thread(detect_pii, query)
        if not pii:
            return query
        redacted = redact_pii(query, pii)
        entity_types = sorted({str(item["entity_type"]) for item in pii})
        if pii_action is None:
            if not policy.pii_require_consent:
                return redacted
            raise GuardrailConsentRequiredError(
                redacted_preview=redacted,
                entities=entity_types,
                allowed_actions=(["redact", "reject"] + (["send_as_is"] if policy.pii_allow_send_as_is else [])),
            )
        if pii_action == "reject":
            raise GuardrailBlockedError(
                "This request was cancelled because it contains personal information."
            )
        if pii_action == "redact":
            return redacted
        if pii_action == "send_as_is" and policy.pii_allow_send_as_is:
            return query
        raise GuardrailBlockedError(
            "Your organization does not allow sending detected personal information as-is."
        )

    def _prepare_conversation(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID | None,
        request_id: UUID,
        metadata: dict | None = None,
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
                    metadata=metadata,
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
    def _config(conversation_id: UUID, checkpoint_id: str | None = None, path_id: UUID | None = None) -> dict[str, Any]:
        configurable = {"thread_id": str(path_id or conversation_id)}
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id
        return {"configurable": configurable}

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
        path_group_id: UUID | None = None,
        assistant_message_id: UUID | None = None,
        path_id: UUID | None = None,
    ) -> None:
        if self.checkpointer is not None and hasattr(graph, "aupdate_state"):
            state_update: dict[str, Any] = {
                "messages": [
                    AIMessage(
                        id=f"assistant:{request_id}",
                        content=response.answer,
                    )
                ]
            }
            if response.guardrail_decision:
                state_update["guardrail_decision"] = response.guardrail_decision
                state_update["guardrail_categories"] = response.guardrail_categories
            # ainvoke may have resumed from an older checkpoint. Resolve the actual
            # head written by that invocation before appending the assistant message;
            # reusing the input config would fork again from the stale parent.
            latest_state = None
            if hasattr(graph, "aget_state"):
                latest_state = await graph.aget_state({"configurable": {"thread_id": str(path_id or conversation.id)}})
            assistant_config = getattr(latest_state, "config", None) or config
            checkpoint_config = await graph.aupdate_state(assistant_config, state_update)
            configurable = (checkpoint_config or {}).get("configurable", {})
            response.checkpoint_id = configurable.get("checkpoint_id")
        response.path_group_id = path_group_id
        response.path_id = path_id
        response.checkpoint_thread_id = str(path_id or conversation.id)
        if path_id is not None:
            path = self.session.get(ConversationPath, path_id)
            if path is not None:
                path.head_checkpoint_id = response.checkpoint_id
                self.session.commit()
        self.conversations.append_assistant_message(
            conversation=conversation,
            request_id=request_id,
            content=response.answer,
            metadata=response.model_dump(mode="json"),
            message_id=assistant_message_id,
            path_id=path_id,
        )

    async def _persist_guardrail_turn(
        self,
        *,
        graph: Any,
        config: dict[str, Any],
        conversation: Conversation,
        request_id: UUID,
        query: str,
        message: str,
        findings: list[dict[str, Any]],
        path_group_id: UUID | None = None,
        assistant_message_id: UUID | None = None,
        path_id: UUID | None = None,
        decision: str = "blocked",
    ) -> GenerationResponse:
        """Persist a guardrail decision as the assistant turn in both stores."""
        response = GenerationResponse(
            generation_id=None,
            conversation_id=conversation.id,
            request_id=request_id,
            query=query,
            answer=message,
            status=GenerationStatus.PARTIAL,
            citations=[],
            warnings=[],
            missing_information=[],
            retrieval_attempts=0,
            evidence_count=0,
            guardrail_decision=decision,
            guardrail_categories=sorted({
                str(item.get("category", "unknown")) for item in findings
            }),
        )
        await self._persist_assistant_turn(
            graph=graph,
            config=config,
            conversation=conversation,
            request_id=request_id,
            response=response,
            path_group_id=path_group_id,
            assistant_message_id=assistant_message_id,
            path_id=path_id,
        )
        return response

    async def _inspect_final_output(
        self, *, query: str, result: dict[str, Any], policy,
        organization_id: UUID, user_id: UUID, request_id: UUID,
    ) -> str:
        answer = result.get("generation_output")
        validation = result.get("validation_result")
        if answer is None or validation is None:
            raise GenerationExecutionError("Output validation requires a complete generated answer.")
        markdown = _append_references(answer.segments[0].text, validation.citations)
        if not policy.output_guardrails_enabled:
            return markdown
        effective = policy.model_copy(deep=True)
        if result.get("topicality_decision") == "off_topic":
            effective.output_enabled["off_topic"] = False
            effective.output_enabled["grounding"] = False
        if not (result.get("retrieved_documents") or []):
            effective.output_enabled["grounding"] = False
        checked = await RuntimeGuardrailService().inspect_output(
            answer=markdown,
            query=query,
            history=result.get("messages") or [],
            policy=effective,
            evidence=result.get("retrieved_documents") or [],
        )
        self._persist_guardrail_audit(
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            stage="output",
            decision="block" if checked["blocked_findings"] else (
                "redact" if checked["transformed_answer"] != markdown else "allow"
            ),
            findings=checked["findings"],
            policy=policy,
        )
        if checked["blocked_findings"]:
            raise GuardrailBlockedError(
                "The generated response was stopped by output guardrails.",
                checked["blocked_findings"],
            )
        return checked["transformed_answer"]

    def _validated_response(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
        result: dict[str, Any],
        answer_markdown_override: str | None = None,
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

        answer_markdown = answer_markdown_override or _append_references(
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
        checkpoint_id: str | None = None,
        path_group_id: UUID | None = None,
        path_id: UUID | None = None,
        request_id: UUID | None = None,
        user_message_id: UUID | None = None,
        assistant_message_id: UUID | None = None,
        pii_action: str | None = None,
        images: list[Any] | None = None,
    ) -> GenerationResponse:
        request_id = request_id or uuid4()
        existing_response = self._existing_idempotent_response(
            organization_id=organization_id, user_id=user_id,
            conversation_id=conversation_id, request_id=request_id,
        )
        if existing_response is not None:
            return existing_response
        if not query.strip() and images:
            query = "Please analyze the attached image(s) and respond helpfully."
        policy = self._effective_guardrail_policy(organization_id)
        original_query = query
        try:
            query = await self._prepare_guarded_query(
                query=query, policy=policy, pii_action=pii_action
            )
        except GuardrailConsentRequiredError:
            self._persist_guardrail_audit(
                organization_id=organization_id, user_id=user_id,
                request_id=request_id, stage="input", decision="consent_required",
                findings=[{"category": "pii", "confidence": 1.0}], policy=policy,
            )
            raise
        except GuardrailBlockedError:
            self._persist_guardrail_audit(
                organization_id=organization_id, user_id=user_id,
                request_id=request_id, stage="input", decision="block",
                findings=[{"category": "pii", "confidence": 1.0}], policy=policy,
            )
            raise
        image_metadata = prepare_image_attachments(
            images or [],
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
        )
        query_was_redacted = query != original_query
        message_metadata = {
            **({"guardrail_decision": "redacted"} if query_was_redacted else {}),
            **({"attachments": image_metadata} if image_metadata else {}),
            **({"path_group_id": str(path_group_id)} if path_group_id else {}),
        } or None
        conversation = self._prepare_conversation(
            query=query,
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            metadata=message_metadata,
        )
        if path_id is not None:
            path = self.session.scalar(select(ConversationPath).where(
                ConversationPath.id == path_id, ConversationPath.conversation_id == conversation.id,
            ))
            if path is None:
                raise ValueError("The selected conversation timeline does not belong to this conversation.")
            if checkpoint_id and path.head_checkpoint_id != checkpoint_id:
                raise ValueError("The selected timeline checkpoint is stale. Reload the conversation and retry.")
        async with conversation_thread_lock(conversation.id):
            self.conversations.append_user_message(
                conversation=conversation,
                request_id=request_id,
                content=query,
                metadata={**({"guardrail_decision": "redacted"} if query_was_redacted else {}), **({"attachments": image_metadata} if image_metadata else {}), **({"path_group_id": str(path_group_id)} if path_group_id else {})} or None,
                message_id=user_message_id,
                path_id=path_id,
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

            config = self._config(conversation.id, checkpoint_id, path_id)
            graph = await self._create_graph()
            graph_input = {
                "query": query,
                "organization_id": organization_id,
                "user_id": user_id,
                "request_id": str(request_id),
                "messages": [HumanMessage(
                    id=str(request_id),
                    content=query,
                    additional_kwargs={"image_attachments": image_metadata} if image_metadata else {},
                )],
                "effective_guardrail_policy": policy.model_dump(mode="json"),
                **(
                    {"guardrail_decision": "redacted", "guardrail_categories": ["pii"]}
                    if query_was_redacted else {}
                ),
            }
            try:
                result = await graph.ainvoke(
                    graph_input,
                    config=config if self.checkpointer is not None else None,
                )
            except GuardrailBlockedError as exc:
                self._persist_guardrail_audit(
                    organization_id=organization_id, user_id=user_id,
                    request_id=request_id, stage="output_stream", decision="block",
                    findings=exc.findings, policy=policy,
                )
                response = await self._persist_guardrail_turn(
                    graph=graph, config=config, conversation=conversation,
                    request_id=request_id, query=query, message=exc.message,
                    findings=exc.findings, path_group_id=path_group_id, assistant_message_id=assistant_message_id,
                    path_id=path_id,
                )
                return response
            except Exception as exc:
                logger.exception(
                    "Persistent RAG execution failed (conversation_id=%s).",
                    conversation.id,
                )
                raise GenerationExecutionError(
                    "The configured model does not support image input. Please switch to a vision-capable model or send a text-only message."
                    if image_metadata and _vision_compatibility_error(exc)
                    else "The generation workflow failed."
                ) from exc

            if result.get("is_valid") is not True:
                return self._validated_response(
                    query=query, organization_id=organization_id, user_id=user_id,
                    conversation_id=conversation.id, request_id=request_id, result=result,
                )
            input_findings = result.get("input_guardrail_findings") or []
            input_blocked = result.get("input_guardrail_blocked") is True
            self._persist_guardrail_audit(
                organization_id=organization_id, user_id=user_id,
                request_id=request_id, stage="input",
                decision="block" if input_blocked else (
                    "redirect" if result.get("topicality_decision") == "off_topic" else "allow"
                ),
                findings=input_findings, policy=policy,
            )
            if input_blocked:
                response = await self._persist_guardrail_turn(
                    graph=graph, config=config, conversation=conversation,
                    request_id=request_id, query=query,
                    message=(result.get("generation_output").segments[0].text
                             if result.get("generation_output") else
                             result.get("input_guardrail_message") or
                             "The request was blocked by organization guardrails."),
                    findings=input_findings, path_group_id=path_group_id, assistant_message_id=assistant_message_id,
                    path_id=path_id,
                )
                await emit({"type": "completed", "result": response.model_dump(mode="json")})
                return response
            try:
                output_markdown = await self._inspect_final_output(
                    query=query, result=result, policy=policy,
                    organization_id=organization_id, user_id=user_id, request_id=request_id,
                )
            except GuardrailBlockedError as exc:
                response = await self._persist_guardrail_turn(
                    graph=graph, config=config, conversation=conversation,
                    request_id=request_id, query=query, message=exc.message,
                    findings=exc.findings, path_group_id=path_group_id, assistant_message_id=assistant_message_id,
                    path_id=path_id,
                )
                await emit({"type": "completed", "result": response.model_dump(mode="json")})
                return response
            response = self._validated_response(
                query=query,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation.id,
                request_id=request_id,
                result=result,
                answer_markdown_override=output_markdown,
            )
            await self._persist_assistant_turn(
                graph=graph,
                config=config,
                conversation=conversation,
                request_id=request_id,
                response=response,
                path_group_id=path_group_id,
                assistant_message_id=assistant_message_id,
                path_id=path_id,
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
        checkpoint_id: str | None = None,
        path_group_id: UUID | None = None,
        path_id: UUID | None = None,
        request_id: UUID | None = None,
        user_message_id: UUID | None = None,
        assistant_message_id: UUID | None = None,
        pii_action: str | None = None,
        images: list[Any] | None = None,
        on_event: Callable[[dict[str, Any]], Any],
    ) -> GenerationResponse:
        request_id = request_id or uuid4()
        existing_response = self._existing_idempotent_response(
            organization_id=organization_id, user_id=user_id,
            conversation_id=conversation_id, request_id=request_id,
        )
        if existing_response is not None:
            return existing_response
        if not query.strip() and images:
            query = "Please analyze the attached image(s) and respond helpfully."
        policy = self._effective_guardrail_policy(organization_id)
        original_query = query
        try:
            query = await self._prepare_guarded_query(
                query=query, policy=policy, pii_action=pii_action
            )
        except GuardrailConsentRequiredError:
            self._persist_guardrail_audit(
                organization_id=organization_id, user_id=user_id,
                request_id=request_id, stage="input", decision="consent_required",
                findings=[{"category": "pii", "confidence": 1.0}], policy=policy,
            )
            raise
        except GuardrailBlockedError:
            self._persist_guardrail_audit(
                organization_id=organization_id, user_id=user_id,
                request_id=request_id, stage="input", decision="block",
                findings=[{"category": "pii", "confidence": 1.0}], policy=policy,
            )
            raise
        image_metadata = prepare_image_attachments(
            images or [],
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
        )
        query_was_redacted = query != original_query
        message_metadata = {
            **({"guardrail_decision": "redacted"} if query_was_redacted else {}),
            **({"attachments": image_metadata} if image_metadata else {}),
            **({"path_group_id": str(path_group_id)} if path_group_id else {}),
        } or None
        conversation = self._prepare_conversation(
            query=query,
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            metadata=message_metadata,
        )
        if path_id is not None:
            path = self.session.scalar(select(ConversationPath).where(
                ConversationPath.id == path_id, ConversationPath.conversation_id == conversation.id,
            ))
            if path is None:
                raise ValueError("The selected conversation timeline does not belong to this conversation.")
            if checkpoint_id and path.head_checkpoint_id != checkpoint_id:
                raise ValueError("The selected timeline checkpoint is stale. Reload the conversation and retry.")

        async def emit(event: dict[str, Any]) -> None:
            result = on_event(event)
            if hasattr(result, "__await__"):
                await result

        async with conversation_thread_lock(conversation.id):
            self.conversations.append_user_message(
                conversation=conversation,
                request_id=request_id,
                content=query,
                metadata={**({"guardrail_decision": "redacted"} if query_was_redacted else {}), **({"attachments": image_metadata} if image_metadata else {}), **({"path_group_id": str(path_group_id)} if path_group_id else {})} or None,
                message_id=user_message_id,
                path_id=path_id,
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

            config = self._config(conversation.id, checkpoint_id, path_id)
            graph = await self._create_graph(on_event=emit)
            graph_input = {
                "query": query,
                "organization_id": organization_id,
                "user_id": user_id,
                "request_id": str(request_id),
                "messages": [HumanMessage(
                    id=str(request_id),
                    content=query,
                    additional_kwargs={"image_attachments": image_metadata} if image_metadata else {},
                )],
                "effective_guardrail_policy": policy.model_dump(mode="json"),
                **(
                    {"guardrail_decision": "redacted", "guardrail_categories": ["pii"]}
                    if query_was_redacted else {}
                ),
            }
            try:
                result = await graph.ainvoke(
                    graph_input,
                    config=config if self.checkpointer is not None else None,
                )
            except GuardrailBlockedError as exc:
                self._persist_guardrail_audit(
                    organization_id=organization_id, user_id=user_id,
                    request_id=request_id, stage="output_stream", decision="block",
                    findings=exc.findings, policy=policy,
                )
                response = await self._persist_guardrail_turn(
                    graph=graph, config=config, conversation=conversation,
                    request_id=request_id, query=query, message=exc.message,
                    findings=exc.findings, path_group_id=path_group_id, assistant_message_id=assistant_message_id,
                    path_id=path_id,
                )
                await emit({"type": "completed", "result": response.model_dump(mode="json")})
                return response
            except Exception as exc:
                logger.exception(
                    "Persistent streaming RAG failed (conversation_id=%s).",
                    conversation.id,
                )
                raise GenerationExecutionError(
                    (
                        "The configured model does not support image input. Please switch to a vision-capable model or send a text-only message."
                        if image_metadata and _vision_compatibility_error(exc)
                        else "The streaming generation workflow failed."
                    )
                ) from exc

            if result.get("is_valid") is not True:
                return self._validated_response(
                    query=query, organization_id=organization_id, user_id=user_id,
                    conversation_id=conversation.id, request_id=request_id, result=result,
                )
            input_findings = result.get("input_guardrail_findings") or []
            input_blocked = result.get("input_guardrail_blocked") is True
            self._persist_guardrail_audit(
                organization_id=organization_id, user_id=user_id,
                request_id=request_id, stage="input",
                decision="block" if input_blocked else (
                    "redirect" if result.get("topicality_decision") == "off_topic" else "allow"
                ),
                findings=input_findings, policy=policy,
            )
            if input_blocked:
                response = await self._persist_guardrail_turn(
                    graph=graph, config=config, conversation=conversation,
                    request_id=request_id, query=query,
                    message=(result.get("generation_output").segments[0].text
                             if result.get("generation_output") else
                             result.get("input_guardrail_message") or
                             "The request was blocked by organization guardrails."),
                    findings=input_findings, path_group_id=path_group_id, assistant_message_id=assistant_message_id,
                    path_id=path_id,
                )
                return response
            try:
                output_markdown = await self._inspect_final_output(
                    query=query, result=result, policy=policy,
                    organization_id=organization_id, user_id=user_id, request_id=request_id,
                )
            except GuardrailBlockedError as exc:
                response = await self._persist_guardrail_turn(
                    graph=graph, config=config, conversation=conversation,
                    request_id=request_id, query=query, message=exc.message,
                    findings=exc.findings, path_group_id=path_group_id, assistant_message_id=assistant_message_id,
                    path_id=path_id,
                )
                await emit({"type": "completed", "result": response.model_dump(mode="json")})
                return response
            response = self._validated_response(
                query=query,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation.id,
                request_id=request_id,
                result=result,
                answer_markdown_override=output_markdown,
            )
            await self._persist_assistant_turn(
                graph=graph,
                config=config,
                conversation=conversation,
                request_id=request_id,
                response=response,
                path_group_id=path_group_id,
                assistant_message_id=assistant_message_id,
                path_id=path_id,
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
