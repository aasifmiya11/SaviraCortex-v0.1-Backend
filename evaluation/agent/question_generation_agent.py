"""Evaluation-only agent for generating retrieval question variants."""
from __future__ import annotations

import json
from typing import Any, Sequence

from langchain_core.output_parsers import PydanticOutputParser

from app.core.config import settings
from app.llm.client import llm_client

from .config import QuestionGenerationConfig
from .prompts import get_question_generation_prompt
from .schemas import QuestionGenerationOutput


class QuestionGenerationError(Exception):
    """Base exception for evaluation question-generation errors."""


class EmptyCandidateInputError(QuestionGenerationError):
    """Raised when candidate evidence input is missing or unusable."""


class QuestionGenerationAgent:
    """
    Stateless question-generation agent following the application agent pattern.

    The agent receives conversation context and curated source evidence.
    It does not query Qdrant, invoke the production retriever, generate
    reference answers, or assign relevance grades.
    """

    def __init__(
        self,
        config: QuestionGenerationConfig | None = None,
        client: Any | None = None,
        model: Any | None = None,
    ) -> None:
        self.config = config or QuestionGenerationConfig()

        self.client = client
        self.model = model

        if self.model is None:
            if self.client is None:
                self.model = llm_client.get_llm()
            elif hasattr(self.client, "get_llm"):
                self.model = self.client.get_llm()
            else:
                self.model = self.client

        self.model_name = settings.OPENAI_MODEL
        self.model = self.model.bind(
            temperature=self.config.temperature,
            max_tokens=self.config.max_output_tokens,
        )

        self.parser = PydanticOutputParser(
            pydantic_object=QuestionGenerationOutput
        )

        self.prompt = get_question_generation_prompt(
            max_questions=self.config.max_questions,
            format_instructions=self.parser.get_format_instructions(),
        )

        self.chain = self.prompt | self.model | self.parser

    @staticmethod
    def _validate_inputs(
        candidate_id: str,
        context: Sequence[dict[str, str]],
        evidence_chunks: Sequence[dict[str, Any]],
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise EmptyCandidateInputError("candidate_id cannot be empty.")

        normalized_context: list[dict[str, str]] = []
        for index, message in enumerate(context):
            if not isinstance(message, dict):
                raise TypeError(f"Context message {index} must be a dictionary.")
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"}:
                raise ValueError(
                    f"Context message {index} must have user or assistant role."
                )
            if not isinstance(content, str) or not content.strip():
                raise ValueError(
                    f"Context message {index} must have non-empty content."
                )
            normalized_context.append({"role": role, "content": content.strip()})

        if len(normalized_context) > 6 or len(normalized_context) % 2:
            raise ValueError(
                "Conversation context must contain zero to three complete exchanges."
            )

        for index, message in enumerate(normalized_context):
            expected_role = "user" if index % 2 == 0 else "assistant"
            if message["role"] != expected_role:
                raise ValueError(
                    "Conversation context must alternate user and assistant messages."
                )

        normalized_chunks: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()
        for index, chunk in enumerate(evidence_chunks):
            if not isinstance(chunk, dict):
                raise TypeError(f"Evidence chunk {index} must be a dictionary.")
            chunk_id = chunk.get("chunk_id")
            chunk_text = chunk.get("text")
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                raise ValueError(f"Evidence chunk {index} has no valid chunk_id.")
            if chunk_id in seen_chunk_ids:
                raise ValueError(f"Duplicate evidence chunk ID: {chunk_id}")
            if not isinstance(chunk_text, str) or not chunk_text.strip():
                raise ValueError(f"Evidence chunk {chunk_id} has no usable text.")
            seen_chunk_ids.add(chunk_id)
            normalized_chunks.append(dict(chunk))

        if not normalized_chunks:
            raise EmptyCandidateInputError(
                "At least one non-empty evidence chunk is required."
            )

        return normalized_context, normalized_chunks

    def generate(
        self,
        candidate_id: str,
        context: Sequence[dict[str, str]],
        retrieved_chunks: Sequence[dict[str, Any]],
    ) -> QuestionGenerationOutput:
        """
        Generate one to three question variants for one evidence candidate.

        retrieved_chunks are curated source/evidence chunks, not results
        returned by the production retriever.
        """
        normalized_context, evidence_chunks = self._validate_inputs(
            candidate_id,
            context,
            retrieved_chunks,
        )

        result = self.chain.invoke(
            {
                "conversation_context": json.dumps(
                    normalized_context,
                    ensure_ascii=False,
                    indent=2,
                ),
                "evidence_chunks": json.dumps(
                    evidence_chunks,
                    ensure_ascii=False,
                    indent=2,
                ),
            },
            config={
                "metadata": {
                    "agent": "evaluation_question_generation",
                    "candidate_id": candidate_id,
                }
            },
        )

        if not isinstance(result, QuestionGenerationOutput):
            result = QuestionGenerationOutput.model_validate(result)

        if not normalized_context and any(
            item.style != "self_contained" for item in result.questions
        ):
            raise QuestionGenerationError(
                "Candidates without conversation history must produce only "
                "self-contained questions."
            )

        if len(result.questions) > self.config.max_questions:
            raise QuestionGenerationError(
                "Generated question count exceeds the configured maximum."
            )

        return result
