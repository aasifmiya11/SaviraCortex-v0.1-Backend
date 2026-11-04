from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser

from app.llm.context_compression_client import context_compression_llm_client

from .config import ContextCompressionConfig
from .prompts import get_context_compression_prompt
from .schemas import ContextCompressionOutput


class ContextCompressionError(ValueError):
    """Base exception for context-compression errors."""


class InvalidCompressionInputError(ContextCompressionError):
    """Raised when compression inputs are invalid."""


class ContextCompressionAgent:
    """Compress each candidate one-to-one, retaining its original identity.

    Threshold estimation uses ceil(character_count / chars_per_token). This
    deterministic estimate is for routing only, not provider token accounting.
    """

    def __init__(
        self,
        config: ContextCompressionConfig | None = None,
        model: Any | None = None,
    ) -> None:
        self.config = config or ContextCompressionConfig()
        self.llm = model or context_compression_llm_client.get_llm(
            temperature=self.config.temperature,
            max_output_tokens=self.config.max_output_tokens,
        )
        self.parser = PydanticOutputParser(
            pydantic_object=ContextCompressionOutput,
        )
        self.prompt = get_context_compression_prompt(
            format_instructions=self.parser.get_format_instructions(),
        )
        self.chain = self.prompt | self.llm | self.parser

    @staticmethod
    def _validate_inputs(
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> None:
        if not isinstance(current_query, str) or not current_query.strip():
            raise InvalidCompressionInputError("Current query cannot be empty.")
        if isinstance(retrieved_documents, (str, bytes)) or not retrieved_documents:
            raise InvalidCompressionInputError(
                "At least one retrieved document is required."
            )
        for index, document in enumerate(retrieved_documents, start=1):
            if not isinstance(document, dict):
                raise TypeError(f"Retrieved document at position {index} must be a dictionary.")
            if not isinstance(document.get("page_content"), str):
                raise InvalidCompressionInputError(
                    f"page_content at position {index} must be a string."
                )
            metadata = document.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise TypeError(f"Metadata at document position {index} must be a dictionary.")

    def estimate_token_count(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> int:
        self._validate_inputs(current_query, retrieved_documents)
        total_chars = len(current_query) + sum(
            len(document["page_content"]) for document in retrieved_documents
        )
        return math.ceil(total_chars / self.config.chars_per_token)

    def should_compress(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> bool:
        return self.estimate_token_count(current_query, retrieved_documents) > self.config.token_threshold

    @staticmethod
    def _prepare_documents(
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {"index": index, "content": document["page_content"]}
            for index, document in enumerate(retrieved_documents, start=1)
        ]

    @staticmethod
    def _apply_compression(
        retrieved_documents: Sequence[dict[str, Any]],
        result: ContextCompressionOutput,
    ) -> list[dict[str, Any]]:
        expected = list(range(1, len(retrieved_documents) + 1))
        actual = [item.index for item in result.documents]
        if actual != expected:
            raise ContextCompressionError(
                "Compression output must contain exactly one result per input "
                "document, in the original order, with matching indexes."
            )

        compressed = []
        for original, item in zip(retrieved_documents, result.documents):
            updated = dict(original)
            updated["page_content"] = item.compressed_content
            compressed.append(updated)
        return compressed

    def compress(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Compress all documents in one structured model request."""
        self._validate_inputs(current_query, retrieved_documents)
        payload = {
            "query_json": json.dumps(current_query, ensure_ascii=False),
            "documents_json": json.dumps(
                self._prepare_documents(retrieved_documents),
                ensure_ascii=False,
            ),
        }
        result = self.chain.invoke(
            payload, config={"metadata": {"agent": "context_compression"}}
        )
        if not isinstance(result, ContextCompressionOutput):
            result = ContextCompressionOutput.model_validate(result)
        return self._apply_compression(retrieved_documents, result)

    async def acompress(
        self,
        current_query: str,
        retrieved_documents: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Asynchronous counterpart to compress()."""
        self._validate_inputs(current_query, retrieved_documents)
        payload = {
            "query_json": json.dumps(current_query, ensure_ascii=False),
            "documents_json": json.dumps(
                self._prepare_documents(retrieved_documents),
                ensure_ascii=False,
            ),
        }
        result = await self.chain.ainvoke(
            payload, config={"metadata": {"agent": "context_compression"}}
        )
        if not isinstance(result, ContextCompressionOutput):
            result = ContextCompressionOutput.model_validate(result)
        return self._apply_compression(retrieved_documents, result)
