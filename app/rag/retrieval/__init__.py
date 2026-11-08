"""Retrieval components.

Keep package imports lazy: importing a standalone component such as the
reranker must not initialize Qdrant or make network calls.
"""

from __future__ import annotations

from typing import Any

__all__ = ["HybridRetrievalPipeline", "retrieval_pipeline"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .pipeline import HybridRetrievalPipeline, retrieval_pipeline

        return {
            "HybridRetrievalPipeline": HybridRetrievalPipeline,
            "retrieval_pipeline": retrieval_pipeline,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
