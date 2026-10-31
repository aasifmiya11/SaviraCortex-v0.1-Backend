"""
app/rag/embedding.py

Local Hugging Face embedding client for LangChain Documents.
The model is initialized once when this module is imported.
"""

from __future__ import annotations

from typing import Sequence

import torch
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings


class HuggingFaceEmbeddingClient:
    """Create and manage local Sentence Transformers embeddings."""

    DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        cache_folder: str | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1.")

        selected_device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.model_name = model_name
        self.device = selected_device

        self.embedding_model = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": selected_device},
            encode_kwargs={
                "batch_size": batch_size,
                "normalize_embeddings": normalize_embeddings,
            },
            query_encode_kwargs={
                "normalize_embeddings": normalize_embeddings,
            },
            cache_folder=cache_folder,
            show_progress=True,
        )

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate one vector for each non-empty input string."""
        cleaned = [
            text.strip()
            for text in texts
            if isinstance(text, str) and text.strip()
        ]
        return self.embedding_model.embed_documents(cleaned) if cleaned else []

    def embed_documents(
        self, documents: Sequence[Document]
    ) -> list[list[float]]:
        """
        Generate vectors for non-empty LangChain Documents.
        Output order matches the non-empty input documents.
        """
        texts = [
            doc.page_content.strip()
            for doc in documents
            if doc.page_content and doc.page_content.strip()
        ]
        return self.embedding_model.embed_documents(texts) if texts else []

    def embed_query(self, query: str) -> list[float]:
        """Generate an embedding vector for a query."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string.")
        return self.embedding_model.embed_query(query.strip())

    def get_embedding_model(self) -> HuggingFaceEmbeddings:
        """Return the underlying LangChain Embeddings object for vector stores."""
        return self.embedding_model


# One model instance per server process.
embedding_client = HuggingFaceEmbeddingClient()
embedding_model = embedding_client.get_embedding_model()

if __name__ == "__main__":
    # Example usage
    client = HuggingFaceEmbeddingClient()
    texts = ["Hello world!", "This is a test.", "   ", ""]
    embeddings = client.embed_texts(texts)
    print(embeddings)