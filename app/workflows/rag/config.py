"""Configuration for the end-to-end RAG workflow."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RAGWorkflowConfig:
    """Controls workflow retry and context-compression routing."""

    max_retrieval_attempts: int = 3
    compression_document_threshold: int = 15

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_retrieval_attempts, bool)
            or not isinstance(self.max_retrieval_attempts, int)
            or self.max_retrieval_attempts < 1
        ):
            raise ValueError("max_retrieval_attempts must be a positive integer.")

        if (
            isinstance(self.compression_document_threshold, bool)
            or not isinstance(self.compression_document_threshold, int)
            or self.compression_document_threshold < 0
        ):
            raise ValueError(
                "compression_document_threshold must be a non-negative integer."
            )
