"""Select the configured embedding provider for application-wide use."""

from ...core.config import settings
from .jina_embeddings import JinaEmbeddingClient
from .cloudflare_embeddings import CloudflareEmbeddingClient


if settings.EMBEDDING_PROVIDER == "cloudflare":
    embedding_client = CloudflareEmbeddingClient()
else:
    embedding_client = JinaEmbeddingClient()

# LangChain vector stores consume this same selected provider instance.
embedding_model = embedding_client
