from __future__ import annotations

from typing import Sequence

from langchain_core.documents import Document
from langchain_core.output_parsers import PydanticOutputParser

from ...llm.client import llm_client

from .config import DocumentSummarizerConfig
from .prompts import get_document_summarizer_prompt
from .schemas import DocumentSummarizerOutput


class DocumentSummarizerError(Exception):
    """Base exception for document summarization errors."""


class EmptyDocumentInputError(DocumentSummarizerError):
    """Raised when no usable document content is provided."""


class DocumentSummarizerAgent:
    """
    Stateless Document Summarizer Agent.

    Responsibilities:
        1. Analyze sampled document pages.
        2. Extract document metadata.
        3. Infer the responsible department.
        4. Generate a document description.
        5. Generate a comprehensive document summary.

    Does not interact with PostgreSQL, Qdrant, or file storage.
    """

    def __init__(
        self,
        config: DocumentSummarizerConfig | None = None,
    ) -> None:

        self.config = config or DocumentSummarizerConfig()

        # Shared LLM instance
        self.llm = llm_client.get_llm()

        # Structured output parser
        self.parser = PydanticOutputParser(
            pydantic_object=DocumentSummarizerOutput
        )

        # Prompt template
        self.prompt = get_document_summarizer_prompt(
            summary_length=self.config.summary_length,
            summary_style=self.config.summary_style,
            language=self.config.language,
            format_instructions=self.parser.get_format_instructions(),
        )

        # Apply agent-specific generation settings
        model = self.llm.bind(
            temperature=self.config.temperature,
            max_tokens=self.config.max_output_tokens,
        )

        # Construct the LangChain pipeline
        self.chain = (
            self.prompt
            | model
            | self.parser
        )

    # =====================================================
    # Input Preparation
    # =====================================================

    @staticmethod
    def _prepare_pages(
        pages: Sequence[Document],
    ) -> str:
        """
        Combine sampled LangChain Documents into one text input.
        """

        if not pages:
            raise EmptyDocumentInputError(
                "No sampled pages were provided."
            )

        formatted_pages = []

        for index, page in enumerate(pages, start=1):

            if not isinstance(page, Document):
                raise TypeError(
                    f"Expected LangChain Document at position {index}, "
                    f"received {type(page).__name__}."
                )

            page_text = page.page_content.strip()

            if not page_text:
                continue

            formatted_pages.append(
                f"[SAMPLED PAGE {index}]\n{page_text}"
            )

        if not formatted_pages:
            raise EmptyDocumentInputError(
                "All supplied sampled pages are empty."
            )

        return "\n\n".join(formatted_pages)

    # =====================================================
    # Summarization
    # =====================================================

    def summarize(
        self,
        pages: Sequence[Document],
    ) -> DocumentSummarizerOutput:
        """
        Generate structured document metadata and summary.

        Args:
            pages:
                Sampled LangChain Documents returned by PDFSampler.

        Returns:
            DocumentSummarizerOutput:
                Validated structured document information.
        """

        # Prepare sampled page contents
        document_text = self._prepare_pages(pages)

        # Execute LangChain pipeline:
        # PromptTemplate -> ChatOpenAI -> PydanticOutputParser
        result = self.chain.invoke(
            {
                "document_text": document_text,
            }
        )

        return result