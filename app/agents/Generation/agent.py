from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser

from app.llm.generator_client import generator_llm_client
from app.validation import InvalidCitationReferenceError, static_validation_layer

from .config import GenerationConfig
from .prompts import get_generation_prompt
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
        self.chain = self.prompt | self.llm | StrOutputParser()
        self.streaming_chain = self.prompt | self.llm | StrOutputParser()

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

    def generate(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None = None,
        status: GenerationStatus = GenerationStatus.ANSWERED,
        long_term_memories: Sequence[dict[str, Any]] | None = None,
    ) -> GenerationOutput:
        evidence = self._prepare_evidence(retrieved_documents)
        if not evidence:
            return self._insufficient_evidence_output()
        markdown = self.chain.invoke(
            self._build_payload(current_query, evidence, conversation_history, long_term_memories),
            config={"metadata": {"agent": "generation"}},
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
        if not evidence:
            return self._insufficient_evidence_output()
        markdown = await self.chain.ainvoke(
            self._build_payload(current_query, evidence, conversation_history, long_term_memories),
            config={"metadata": {"agent": "generation"}},
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
        if not evidence:
            yield GenerationStreamEvent(
                event_type=GenerationStreamEventType.COMPLETED,
                output=self._insufficient_evidence_output(),
            )
            return

        chunks: list[str] = []
        async for chunk in self.streaming_chain.astream(
            self._build_payload(current_query, evidence, conversation_history, long_term_memories),
            config={"metadata": {"agent": "generation"}},
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
