from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings
from app.llm.generator_client import generator_llm_client
from app.llm.model_router import ModelRoute, ModelRouter
from app.validation import InvalidCitationReferenceError, static_validation_layer

from .config import GenerationConfig
from .prompts import get_generation_prompt, get_generation_system_instructions
from .schemas import (
    AnswerSegment,
    GenerationOutput,
    GenerationStatus,
    GenerationStreamEvent,
    GenerationStreamEventType,
)


class GenerationAgentError(Exception):
    """Base exception for generation-agent errors."""


class CitationValidationError(GenerationAgentError):
    """Raised when the model cites an evidence item absent from this request."""

    def __init__(self, invalid_citations: Sequence[str]) -> None:
        self.invalid_citations = tuple(dict.fromkeys(invalid_citations))
        citation_list = ", ".join(self.invalid_citations)
        super().__init__(f"Generation returned unknown evidence citation(s): {citation_list}")


class GenerationAgent:
    """Generate plain Markdown and validate its numeric evidence markers."""

    INSUFFICIENT_EVIDENCE_MESSAGE = (
        "I don't have enough information in the available company documents "
        "to answer that. Please ask me something related to the available "
        "company information."
    )
    _CITATION_PATTERN = re.compile(r"(?<!\!)\[(\d+)\]")

    def __init__(
        self,
        config: GenerationConfig | None = None,
        model: Any | None = None,
    ) -> None:
        self.config = config or GenerationConfig()
        self.llm = model or generator_llm_client.get_llm(
            temperature=self.config.temperature,
            max_output_tokens=self.config.max_output_tokens,
        )
        self.prompt = get_generation_prompt()
        self.vision_prompt = get_generation_prompt(multimodal=True)
        self.chain = self.prompt | self.llm | StrOutputParser()
        self.streaming_chain = self.prompt | self.llm | StrOutputParser()
        self.model_router = ModelRouter()
        self._vision_llm: Any | None = None
        self._vision_chain: Any | None = None

    @staticmethod
    def _prepare_evidence(
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Expose ordered evidence and safe descriptive metadata to the LLM."""
        evidence: list[dict[str, Any]] = []
        for candidate in retrieved_documents:
            if not isinstance(candidate, dict):
                raise TypeError("Every retrieved candidate must be a dictionary.")
            content = candidate.get("page_content")
            if not isinstance(content, str) or not content.strip():
                continue
            metadata = candidate.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise TypeError("Retrieved candidate metadata must be a dictionary.")

            item: dict[str, Any] = {
                "evidence_id": f"E{len(evidence) + 1}",
                "content": content.strip(),
            }
            document_title = (
                metadata.get("document_title")
                or metadata.get("source_filename")
                or metadata.get("source")
            )
            if isinstance(document_title, str) and document_title.strip():
                item["document"] = document_title.strip()
            page = metadata.get("page")
            if page is not None:
                item["page"] = page
            section = metadata.get("section_heading") or metadata.get("section")
            if isinstance(section, str) and section.strip():
                item["section"] = section.strip()
            if metadata.get("prompt_injection_flagged") is True:
                item["security_label"] = "PROMPT_INJECTION_FLAGGED"
                decision = metadata.get("security_review_decision")
                if isinstance(decision, str) and decision.strip():
                    item["security_decision"] = decision.strip()
            evidence.append(item)
        return evidence

    @staticmethod
    def _build_payload(
        current_query: str,
        evidence: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None,
        long_term_memories: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "current_query_json": json.dumps(current_query, ensure_ascii=False),
            "conversation_history": list(conversation_history or []),
            "long_term_memory_json": json.dumps(
                list(long_term_memories or []), ensure_ascii=False
            ),
            "retrieved_evidence_json": json.dumps(evidence, ensure_ascii=False),
        }

    @classmethod
    def _citation_ids(cls, markdown: str) -> list[str]:
        """Translate user-facing [1] markers to request-scoped E1 IDs."""
        return list(dict.fromkeys(
            f"E{int(number)}"
            for number in cls._CITATION_PATTERN.findall(markdown)
        ))

    @classmethod
    def _build_output(
        cls,
        markdown: str,
        evidence: Sequence[dict[str, Any]],
        status: GenerationStatus,
    ) -> GenerationOutput:
        markdown = markdown.strip()
        if not markdown:
            raise GenerationAgentError("The model returned an empty Markdown answer.")
        output = GenerationOutput(
            status=status,
            segments=[
                AnswerSegment(
                    text=markdown,
                    citations=cls._citation_ids(markdown),
                )
            ],
        )
        return cls.validate_citations(output, evidence)

    @staticmethod
    def _insufficient_evidence_output() -> GenerationOutput:
        return GenerationOutput(
            status=GenerationStatus.INSUFFICIENT_EVIDENCE,
            segments=[
                AnswerSegment(
                    text=GenerationAgent.INSUFFICIENT_EVIDENCE_MESSAGE,
                    citations=[],
                )
            ],
        )

    @staticmethod
    def validate_citations(
        output: GenerationOutput,
        evidence: Sequence[dict[str, Any]],
    ) -> GenerationOutput:
        """Check every numeric citation against this request's evidence list."""
        try:
            return static_validation_layer.validate_citation_ids(output, evidence)
        except InvalidCitationReferenceError as exc:
            raise CitationValidationError(exc.invalid_citations) from exc

    @staticmethod
    def _has_image_input(history: Sequence[BaseMessage] | None) -> bool:
        return ModelRouter.has_image_input(history)

    def _select_chain(
        self,
        conversation_history: Sequence[BaseMessage] | None,
    ) -> tuple[Any, bool]:
        route = self.model_router.select_route(conversation_history)
        if route is ModelRoute.TEXT:
            return self.chain, False
        if self._vision_chain is None:
            self._vision_llm = generator_llm_client.get_vision_llm(
                temperature=self.config.temperature,
                max_output_tokens=settings.OPENAI_VISION_MAX_OUTPUT_TOKENS,
            )
            self._vision_chain = self.vision_prompt | self._vision_llm | StrOutputParser()
        return self._vision_chain, True

    @staticmethod
    def _build_vision_payload(
        current_query: str,
        evidence: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None,
        long_term_memories: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # Keep the vision request compact for Palmyra Vision's 4K-token context.
        compact_evidence = [
            {**item, "content": str(item.get("content", ""))[:600]}
            for item in list(evidence)[:2]
        ]
        history = list(conversation_history or [])
        current_image_message: BaseMessage | None = None
        if history and ModelRouter.has_image_input([history[-1]]) and isinstance(history[-1], HumanMessage):
            current_image_message = history.pop()

        compact_history: list[BaseMessage] = []
        for message in history[-3:]:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                compact_content: Any = content[-600:]
            elif isinstance(content, list):
                compact_content = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "image_url":
                        compact_content.append(block)
                    elif block.get("type") == "text":
                        compact_content.append({
                            **block,
                            "text": str(block.get("text", ""))[-500:],
                        })
            else:
                compact_content = content
            try:
                compact_history.append(message.model_copy(update={"content": compact_content}))
            except AttributeError:
                compact_history.append(message.copy(update={"content": compact_content}))

        previous_user_images: list[dict[str, Any]] = []
        previous_user_text = "(none)"
        if compact_history and isinstance(compact_history[-1], HumanMessage):
            # Fold a trailing user turn into the current one to preserve strict
            # user/assistant alternation required by the Bedrock vision endpoint.
            previous_user = compact_history.pop()
            previous_content = previous_user.content
            if isinstance(previous_content, str):
                previous_user_text = previous_content[-500:]
            elif isinstance(previous_content, list):
                previous_text_blocks = [
                    str(block.get("text", ""))[-500:]
                    for block in previous_content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                previous_user_text = "\n".join(previous_text_blocks)
                previous_user_images = [
                    block for block in previous_content
                    if isinstance(block, dict) and block.get("type") == "image_url"
                ]
            else:
                previous_user_text = ""

        prompt_text = (
            "TRUSTED SAVIRACORTEX ASSISTANT INSTRUCTIONS\n"
            + get_generation_system_instructions()
            + "\n\nPREVIOUS USER TURN (UNTRUSTED CONTEXT)\n"
            + previous_user_text
            + "\n\nCURRENT USER QUERY (UNTRUSTED INPUT)\n"
            + json.dumps(current_query[-1200:], ensure_ascii=False)
            + "\n\nRELEVANT LONG-TERM USER CONTEXT (UNTRUSTED CONTEXT)\n"
            + json.dumps(list(long_term_memories or [])[:2], ensure_ascii=False)
            + "\n\nRETRIEVED COMPANY-DOCUMENT EVIDENCE (UNTRUSTED SOURCE CONTENT)\n"
            + json.dumps(compact_evidence, ensure_ascii=False)
        )
        current_content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        current_content.extend(previous_user_images)
        if current_image_message is not None and isinstance(current_image_message.content, list):
            current_content.extend(
                block for block in current_image_message.content
                if isinstance(block, dict) and block.get("type") == "image_url"
            )

        return {
            "conversation_history": compact_history,
            "current_user_message": [HumanMessage(content=current_content)],
        }

    def generate(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None = None,
        status: GenerationStatus = GenerationStatus.ANSWERED,
        long_term_memories: Sequence[dict[str, Any]] | None = None,
    ) -> GenerationOutput:
        evidence = self._prepare_evidence(retrieved_documents)
        if not evidence and not self._has_image_input(conversation_history):
            return self._insufficient_evidence_output()
        chain, use_vision = self._select_chain(conversation_history)
        payload = (
            self._build_vision_payload(current_query, evidence, conversation_history, long_term_memories)
            if use_vision
            else self._build_payload(current_query, evidence, conversation_history, long_term_memories)
        )
        markdown = chain.invoke(
            payload,
            config={"metadata": {"agent": "generation", "model_route": "vision" if use_vision else "text"}},
        )
        return self._build_output(str(markdown), evidence, status)

    async def agenerate(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None = None,
        status: GenerationStatus = GenerationStatus.ANSWERED,
        long_term_memories: Sequence[dict[str, Any]] | None = None,
    ) -> GenerationOutput:
        evidence = self._prepare_evidence(retrieved_documents)
        if not evidence and not self._has_image_input(conversation_history):
            return self._insufficient_evidence_output()
        chain, use_vision = self._select_chain(conversation_history)
        payload = (
            self._build_vision_payload(current_query, evidence, conversation_history, long_term_memories)
            if use_vision
            else self._build_payload(current_query, evidence, conversation_history, long_term_memories)
        )
        markdown = await chain.ainvoke(
            payload,
            config={"metadata": {"agent": "generation", "model_route": "vision" if use_vision else "text"}},
        )
        return self._build_output(str(markdown), evidence, status)

    async def astream_generate(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None = None,
        status: GenerationStatus = GenerationStatus.ANSWERED,
        long_term_memories: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[GenerationStreamEvent]:
        """Stream plain Markdown deltas; emit completion only after citation checks."""
        evidence = self._prepare_evidence(retrieved_documents)
        if not evidence and not self._has_image_input(conversation_history):
            yield GenerationStreamEvent(
                event_type=GenerationStreamEventType.COMPLETED,
                output=self._insufficient_evidence_output(),
            )
            return

        chunks: list[str] = []
        chain, use_vision = self._select_chain(conversation_history)
        if not use_vision:
            chain = self.streaming_chain
        payload = (
            self._build_vision_payload(current_query, evidence, conversation_history, long_term_memories)
            if use_vision
            else self._build_payload(current_query, evidence, conversation_history, long_term_memories)
        )
        async for chunk in chain.astream(
            payload,
            config={"metadata": {"agent": "generation", "model_route": "vision" if use_vision else "text"}},
        ):
            if not isinstance(chunk, str):
                raise GenerationAgentError("The Markdown stream returned an unexpected value.")
            if not chunk:
                continue
            chunks.append(chunk)
            yield GenerationStreamEvent(
                event_type=GenerationStreamEventType.CONTENT_DELTA,
                delta=chunk,
                segment_index=0,
            )

        markdown = "".join(chunks)
        output = self._build_output(markdown, evidence, status)
        yield GenerationStreamEvent(
            event_type=GenerationStreamEventType.COMPLETED,
            output=output,
        )
