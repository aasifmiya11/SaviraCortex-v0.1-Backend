"""DeepEval adapter around SaviraCortex's existing LangChain ChatOpenAI client."""

from __future__ import annotations

from typing import Any

from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel

from app.core.config import settings
from app.llm.client import llm_client


class SaviraDeepEvalLLM(DeepEvalBaseLLM):
    """Expose the project's configured ChatOpenAI client to DeepEval."""

    def __init__(self) -> None:
        self._chat_model = None
        self._model_name = settings.OPENAI_MODEL or "SaviraCortex ChatOpenAI"

    def load_model(self):
        if self._chat_model is None:
            if not settings.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY is not configured.")
            if not settings.OPENAI_MODEL:
                raise RuntimeError("OPENAI_MODEL is not configured.")
            self._chat_model = llm_client.get_llm()
        return self._chat_model

    @staticmethod
    def _content_as_text(response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                str(part.get("text", part)) if isinstance(part, dict) else str(part)
                for part in content
            )
        return str(content)

    def generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        model = self.load_model()
        if schema is None:
            return self._content_as_text(model.invoke(prompt))

        result = model.with_structured_output(schema).invoke(prompt)
        if isinstance(result, schema):
            return result
        if isinstance(result, dict):
            return schema.model_validate(result)
        return schema.model_validate_json(self._content_as_text(result))

    async def a_generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        model = self.load_model()
        if schema is None:
            return self._content_as_text(await model.ainvoke(prompt))

        result = await model.with_structured_output(schema).ainvoke(prompt)
        if isinstance(result, schema):
            return result
        if isinstance(result, dict):
            return schema.model_validate(result)
        return schema.model_validate_json(self._content_as_text(result))

    def get_model_name(self) -> str:
        return self._model_name
