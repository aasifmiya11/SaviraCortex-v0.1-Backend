from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser

from app.llm.retrieval_expansion_client import retrieval_expansion_llm_client

from .config import RetrievalExpansionConfig
from .prompts import get_retrieval_expansion_prompt
from .schemas import RetrievalExpansionOutput


class RetrievalExpansionError(Exception):
    """Base exception for retrieval-expansion errors."""


class InvalidExpansionInputError(RetrievalExpansionError):
    """Raised when required expansion input is missing or invalid."""


class RetrievalExpansionAgent:
    """
    Stateless agent that creates a targeted retrieval query and HyDE-inspired
    hypothetical answer for the next retrieval attempt.

    The hypothetical answer is semantic retrieval guidance only. It is never
    factual evidence and must not be passed to answer generation as evidence.
    """

    def __init__(
        self,
        config: RetrievalExpansionConfig | None = None,
        model: Any | None = None,
    ) -> None:
        self.config = config or RetrievalExpansionConfig()
        self.llm = model or retrieval_expansion_llm_client.get_llm(
            temperature=self.config.temperature,
            max_output_tokens=self.config.max_output_tokens,
        )
        self.parser = PydanticOutputParser(
            pydantic_object=RetrievalExpansionOutput,
        )
        self.prompt = get_retrieval_expansion_prompt(
            format_instructions=self.parser.get_format_instructions(),
        )
        self.chain = self.prompt | self.llm | self.parser

    @staticmethod
    def _validate_inputs(
        original_query: str,
        current_retrieval_query: str | None,
        missing_information: Sequence[str],
    ) -> tuple[str, str, list[str]]:
        if not isinstance(original_query, str) or not original_query.strip():
            raise InvalidExpansionInputError(
                "Original user query cannot be empty."
            )

        current_query = current_retrieval_query or original_query
        if not isinstance(current_query, str) or not current_query.strip():
            raise InvalidExpansionInputError(
                "Current retrieval query cannot be empty."
            )

        if (
            not missing_information
            or isinstance(missing_information, (str, bytes))
        ):
            raise InvalidExpansionInputError(
                "missing_information must contain at least one requirement."
            )

        if any(
            not isinstance(item, str) or not item.strip()
            for item in missing_information
        ):
            raise InvalidExpansionInputError(
                "Every missing-information requirement must be non-empty text."
            )

        normalized = [item.strip() for item in missing_information]
        return original_query.strip(), current_query.strip(), normalized

    @staticmethod
    def _prepare_evidence(
        retrieved_documents: Sequence[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Prepare prompt-safe content without exposing internal identifiers."""
        evidence: list[dict[str, Any]] = []

        for index, candidate in enumerate(retrieved_documents or [], start=1):
            if not isinstance(candidate, dict):
                raise TypeError(
                    f"Retrieved candidate at position {index} must be a dictionary."
                )

            content = candidate.get("page_content")
            if not isinstance(content, str) or not content.strip():
                continue

            metadata = candidate.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise TypeError(
                    f"Metadata at candidate position {index} must be a dictionary."
                )

            item: dict[str, Any] = {"content": content.strip()}

            title = (
                metadata.get("document_title")
                or metadata.get("source_filename")
                or metadata.get("source")
            )
            if isinstance(title, str) and title.strip():
                item["document"] = title.strip()

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
        original_query: str,
        current_retrieval_query: str,
        missing_information: Sequence[str],
        retrieved_evidence: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None,
    ) -> dict[str, Any]:
        return {
            "original_query_json": json.dumps(
                original_query,
                ensure_ascii=False,
            ),
            "current_retrieval_query_json": json.dumps(
                current_retrieval_query,
                ensure_ascii=False,
            ),
            "missing_information_json": json.dumps(
                list(missing_information),
                ensure_ascii=False,
            ),
            "retrieved_evidence_json": json.dumps(
                list(retrieved_evidence),
                ensure_ascii=False,
            ),
            "conversation_history": list(conversation_history or []),
        }

    def expand(
        self,
        original_query: str,
        missing_information: Sequence[str],
        retrieved_documents: Sequence[dict[str, Any]] | None = None,
        conversation_history: Sequence[BaseMessage] | None = None,
        current_retrieval_query: str | None = None,
    ) -> RetrievalExpansionOutput:
        """Generate a focused query and hypothetical answer for retrieval."""
        original, current, missing = self._validate_inputs(
            original_query,
            current_retrieval_query,
            missing_information,
        )
        evidence = self._prepare_evidence(retrieved_documents)

        result = self.chain.invoke(
            self._build_payload(
                original,
                current,
                missing,
                evidence,
                conversation_history,
            ),
            config={"metadata": {"agent": "retrieval_expansion"}},
        )
        if isinstance(result, RetrievalExpansionOutput):
            return result
        return RetrievalExpansionOutput.model_validate(result)

    async def aexpand(
        self,
        original_query: str,
        missing_information: Sequence[str],
        retrieved_documents: Sequence[dict[str, Any]] | None = None,
        conversation_history: Sequence[BaseMessage] | None = None,
        current_retrieval_query: str | None = None,
    ) -> RetrievalExpansionOutput:
        """Asynchronous counterpart to expand()."""
        original, current, missing = self._validate_inputs(
            original_query,
            current_retrieval_query,
            missing_information,
        )
        evidence = self._prepare_evidence(retrieved_documents)

        result = await self.chain.ainvoke(
            self._build_payload(
                original,
                current,
                missing,
                evidence,
                conversation_history,
            ),
            config={"metadata": {"agent": "retrieval_expansion"}},
        )
        if isinstance(result, RetrievalExpansionOutput):
            return result
        return RetrievalExpansionOutput.model_validate(result)
