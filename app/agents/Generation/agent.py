from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser

from app.llm.generator_client import generator_llm_client

from .config import GenerationConfig
from .prompts import get_generation_prompt
from .schemas import (
    AnswerSegment,
    GenerationOutput,
    GenerationStatus,
)


class GenerationAgentError(Exception):
    """Base exception for generation-agent errors."""


class GenerationAgent:
    """
    Stateless company-grounded Generation Agent.

    Responsibilities:
        1. Receive the current query, optional conversation history,
           and the final ranked retrieval candidates.
        2. Prepare prompt-visible evidence with request-scoped evidence IDs.
        3. Invoke the configured LLM once.
        4. Parse the response into the GenerationOutput schema.

    This agent does not perform retrieval, reranking, citation verification,
    source URL resolution, document access, or orchestration.
    """

    INSUFFICIENT_EVIDENCE_MESSAGE = (
        "I don't have enough information in the available company documents "
        "to answer that. Please ask me something related to the available "
        "company information."
    )

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

        self.parser = PydanticOutputParser(
            pydantic_object=GenerationOutput,
        )
        self.prompt = get_generation_prompt(
            format_instructions=self.parser.get_format_instructions(),
        )
        self.chain = self.prompt | self.llm | self.parser

    @staticmethod
    def _prepare_evidence(
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Prepare a minimal prompt representation of ranked retrieval results.

        The order supplied by the retrieval pipeline is preserved. Internal
        storage details, database identifiers, scores, and permissions are
        deliberately excluded from the prompt.
        """
        evidence: list[dict[str, Any]] = []

        for candidate in retrieved_documents:
            if not isinstance(candidate, dict):
                raise TypeError(
                    "Every retrieved candidate must be a dictionary."
                )

            content = candidate.get("page_content")
            if not isinstance(content, str) or not content.strip():
                continue

            metadata = candidate.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise TypeError(
                    "Retrieved candidate metadata must be a dictionary."
                )

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

            section = (
                metadata.get("section_heading")
                or metadata.get("section")
            )
            if isinstance(section, str) and section.strip():
                item["section"] = section.strip()

            evidence.append(item)

        return evidence

    @staticmethod
    def _insufficient_evidence_output() -> GenerationOutput:
        """Return the deterministic no-evidence response without an LLM call."""
        return GenerationOutput(
            status=GenerationStatus.INSUFFICIENT_EVIDENCE,
            segments=[
                AnswerSegment(
                    text=GenerationAgent.INSUFFICIENT_EVIDENCE_MESSAGE,
                    citations=[],
                )
            ],
        )

    def generate(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None = None,
    ) -> GenerationOutput:
        """
        Generate a company-grounded answer from ranked retrieval candidates.

        Args:
            current_query: The current user question.
            retrieved_documents: The retrieval service's selected_candidates
                list, in its existing ranked order.
            conversation_history: Optional chronological HumanMessage and
                AIMessage history. The supplied sequence is not modified.

        Returns:
            A parsed GenerationOutput. Citation IDs are references only;
            citation verification and source resolution are separate stages.
        """
        evidence = self._prepare_evidence(retrieved_documents)
        if not evidence:
            return self._insufficient_evidence_output()

        result = self.chain.invoke(
            {
                "current_query_json": json.dumps(
                    current_query,
                    ensure_ascii=False,
                ),
                "conversation_history": list(conversation_history or []),
                "retrieved_evidence_json": json.dumps(
                    evidence,
                    ensure_ascii=False,
                ),
            },
            config={
                "metadata": {
                    "agent": "generation",
                }
            },
        )

        if isinstance(result, GenerationOutput):
            return result

        return GenerationOutput.model_validate(result)

    async def agenerate(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None = None,
    ) -> GenerationOutput:
        """Asynchronous counterpart to generate()."""
        evidence = self._prepare_evidence(retrieved_documents)
        if not evidence:
            return self._insufficient_evidence_output()

        result = await self.chain.ainvoke(
            {
                "current_query_json": json.dumps(
                    current_query,
                    ensure_ascii=False,
                ),
                "conversation_history": list(conversation_history or []),
                "retrieved_evidence_json": json.dumps(
                    evidence,
                    ensure_ascii=False,
                ),
            },
            config={
                "metadata": {
                    "agent": "generation",
                }
            },
        )

        if isinstance(result, GenerationOutput):
            return result

        return GenerationOutput.model_validate(result)
