
"""
PDF page sampling for document-level inspection and summarization.

The sampler receives page-level LangChain Documents from PDFLoader
and selects representative pages using deterministic, evenly
distributed sampling.
"""

from __future__ import annotations

from langchain_core.documents import Document


class PDFSampler:
    """Select representative pages from an extracted PDF."""

    def __init__(self, max_pages: int = 5) -> None:
        if not isinstance(max_pages, int) or isinstance(max_pages, bool):
            raise TypeError("max_pages must be an integer.")

        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero.")

        self.max_pages = max_pages

    @staticmethod
    def _validate_documents(documents: list[Document]) -> None:
        if not isinstance(documents, list):
            raise TypeError("documents must be a list.")

        for index, document in enumerate(documents):
            if not isinstance(document, Document):
                raise TypeError(
                    f"Item at index {index} must be a LangChain Document."
                )

    @staticmethod
    def _get_sample_indices(
        total_pages: int,
        sample_count: int,
    ) -> list[int]:
        """
        Return evenly distributed, zero-based page indices.

        The first and last pages are included whenever sample_count
        is greater than one.
        """
        if sample_count >= total_pages:
            return list(range(total_pages))

        if sample_count == 1:
            return [0]

        return [
            (index * (total_pages - 1)) // (sample_count - 1)
            for index in range(sample_count)
        ]

    def sample(self, documents: list[Document]) -> list[Document]:
        """
        Select representative pages from extracted PDF documents.

        Returns the original Document objects without modifying
        their content or metadata.
        """
        self._validate_documents(documents)

        total_pages = len(documents)

        if total_pages == 0:
            return []

        if total_pages <= self.max_pages:
            return list(documents)

        indices = self._get_sample_indices(
            total_pages=total_pages,
            sample_count=self.max_pages,
        )

        return [documents[index] for index in indices]

    def sample_with_page_numbers(
        self,
        documents: list[Document],
    ) -> list[tuple[int, Document]]:
        """
        Return sampled documents together with their page numbers.

        Uses the existing 'page' metadata when available.
        Otherwise, uses the original 1-indexed list position.
        """
        sampled_documents = self.sample(documents)

        return [
            (
                int(document.metadata.get("page", index + 1)),
                document,
            )
            for index, document in enumerate(
                sampled_documents
            )
        ] if len(documents) <= self.max_pages else [
            (
                int(documents[index].metadata.get("page", index + 1)),
                documents[index],
            )
            for index in self._get_sample_indices(
                len(documents),
                self.max_pages,
            )
        ]
