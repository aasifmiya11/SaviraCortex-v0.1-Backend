from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.core.config import settings


class RetrievalExpansionLLMClient:
    """Creates the chat model used exclusively by retrieval expansion."""

    def get_llm(
        self,
        *,
        temperature: float = 0.2,
        max_output_tokens: int = 1800,
    ) -> ChatOpenAI:
        return ChatOpenAI(
            model_name=settings.OPENAI_MODEL,
            base_url=settings.OPENAI_BASE_URL,
            api_key=settings.OPENAI_API_KEY,
            temperature=temperature,
            max_tokens=max_output_tokens,
        )


retrieval_expansion_llm_client = RetrievalExpansionLLMClient()
