from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser

from app.llm.evidence_evaluator_client_legacy import evidence_evaluator_llm_client

from .config import EvidenceEvaluatorConfig
from .prompts import get_evidence_evaluator_prompt
from .schemas import EvidenceEvaluation


class EvidenceEvaluatorError(Exception):
    """Base exception for evidence-evaluator errors."""


class EmptyQueryError(EvidenceEvaluatorError):
    """Raised when the current user question is empty."""


class EvidenceEvaluatorAgent:
    """
    Stateless agent that judges the sufficiency of retrieved evidence.

    It evaluates the original user question against the accumulated
    retrieved candidates. Conversation history is used only to resolve
    conversational context and is never treated as factual evidence.
    """

    NO_EVIDENCE_REQUIREMENT = (
        "Relevant company-document evidence for the user's question."
    )

    def __init__(
        self,
        config: EvidenceEvaluatorConfig | None = None,
        model: Any | None = None,
    ) -> None:
        self.config = config or EvidenceEvaluatorConfig()
        self.llm = model or evidence_evaluator_llm_client.get_llm(
            temperature=self.config.temperature,
            max_output_tokens=self.config.max_output_tokens,
        )
        self.parser = PydanticOutputParser(
            pydantic_object=EvidenceEvaluation,
        )
        self.prompt = get_evidence_evaluator_prompt(
            format_instructions=self.parser.get_format_instructions(),
        )
        self.chain = self.prompt | self.llm | self.parser

    @staticmethod
    def _prepare_evidence(
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Prepare ordered, prompt-safe evidence from retrieval candidates."""
        evidence: list[dict[str, Any]] = []

        for index, candidate in enumerate(retrieved_documents, start=1):
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
        current_query: str,
        evidence: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None,
    ) -> dict[str, Any]:
        return {
            "current_query_json": json.dumps(
                current_query,
                ensure_ascii=False,
            ),
            "conversation_history": list(conversation_history or []),
            "retrieved_evidence_json": json.dumps(
                evidence,
                ensure_ascii=False,
            ),
        }

    @staticmethod
    def _no_evidence_result() -> EvidenceEvaluation:
        return EvidenceEvaluation(
            is_sufficient=False,
            missing_information=[EvidenceEvaluatorAgent.NO_EVIDENCE_REQUIREMENT],
        )

    def evaluate(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None = None,
    ) -> EvidenceEvaluation:
        """Evaluate whether the retrieved documents fully support the query."""
        if not isinstance(current_query, str) or not current_query.strip():
            raise EmptyQueryError("Current query cannot be empty.")

        evidence = self._prepare_evidence(retrieved_documents)
        if not evidence:
            return self._no_evidence_result()

        result = self.chain.invoke(
            self._build_payload(
                current_query,
                evidence,
                conversation_history,
            ),
            config={"metadata": {"agent": "evidence_evaluator"}},
        )
        if isinstance(result, EvidenceEvaluation):
            return result
        return EvidenceEvaluation.model_validate(result)

    async def aevaluate(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
        conversation_history: Sequence[BaseMessage] | None = None,
    ) -> EvidenceEvaluation:
        """Asynchronous counterpart to evaluate()."""
        if not isinstance(current_query, str) or not current_query.strip():
            raise EmptyQueryError("Current query cannot be empty.")

        evidence = self._prepare_evidence(retrieved_documents)
        if not evidence:
            return self._no_evidence_result()

        result = await self.chain.ainvoke(
            self._build_payload(
                current_query,
                evidence,
                conversation_history,
            ),
            config={"metadata": {"agent": "evidence_evaluator"}},
        )
        if isinstance(result, EvidenceEvaluation):
            return result
        return EvidenceEvaluation.model_validate(result)
