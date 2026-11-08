"""DeepEval adapter around SaviraCortex's Jina API embeddings."""

from __future__ import annotations

import asyncio
from typing import List

from deepeval.models import DeepEvalBaseEmbeddingModel

from app.rag.embeddings.jina_embeddings import embedding_client


class SaviraDeepEvalEmbeddings(DeepEvalBaseEmbeddingModel):
    """Use the same Jina embedding model as SaviraCortex retrieval."""

    def __init__(self) -> None:
        self._embedding_client = embedding_client

    def load_model(self):
        return self._embedding_client.get_embedding_model()

    def embed_text(self, text: str) -> List[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Embedding input must be a non-empty string.")
        return self._embedding_client.embed_query(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return self._embedding_client.embed_texts(texts)

    async def a_embed_text(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.embed_text, text)

    async def a_embed_texts(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self.embed_texts, texts)

    def get_model_name(self) -> str:
        return self._embedding_client.model_name
