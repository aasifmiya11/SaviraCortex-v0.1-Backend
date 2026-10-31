
"""
PDF ingestion orchestrator.

Pipeline:
1. Extract all pages with native PyMuPDF text extraction.
2. Count non-whitespace characters per page.
3. If a page is below text_threshold, OCR that page only.
4. Keep native text for pages that meet the threshold.
5. Normalize the final page text.
6. Return one ordered LangChain Document per PDF page.

The native_client and ocr_client are imported singleton instances.
They are not recreated for each PDF or each call.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

from rich import print
from langchain_core.documents import Document

# Add project root for direct execution.
project_root = Path(__file__).resolve().parents[3]

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from .native import native_client
from .ocr import ocr_client
from ..ingestion.text_normalizer import TextNormalizer


OCREngine = Literal["easyocr", "tesseract", "fastocr"]


class PDFLoader:
    """Native-first PDF loader with page-level OCR fallback."""

    SUPPORTED_OCR_ENGINES = {"easyocr", "tesseract", "fastocr"}

    def __init__(
        self,
        text_threshold: int = 100,
        ocr_engine: OCREngine = "easyocr",
        ocr_options: dict[str, Any] | None = None,
    ) -> None:

        if not isinstance(text_threshold, int) or isinstance(text_threshold, bool):
            raise TypeError("text_threshold must be an integer.")

        if text_threshold < 0:
            raise ValueError("text_threshold cannot be negative.")

        if ocr_engine not in self.SUPPORTED_OCR_ENGINES:
            raise ValueError(
                f"Unsupported OCR engine {ocr_engine!r}. "
                f"Choose from: {', '.join(sorted(self.SUPPORTED_OCR_ENGINES))}."
            )

        self.text_threshold = text_threshold
        self.ocr_engine = ocr_engine
        self.ocr_options = dict(ocr_options or {})

    @staticmethod
    def _text_length(document: Document) -> int:
        """Count non-whitespace characters in extracted text."""
        return len("".join((document.page_content or "").split()))

    @staticmethod
    def _normalize_documents(
        documents: list[Document],
    ) -> list[Document]:
        """
        Normalize each page independently.

        Preserves the original page metadata and document order.
        """
        normalized_documents: list[Document] = []

        for document in documents:
            normalized_text = TextNormalizer.normalize(
                document.page_content or ""
            )

            normalized_documents.append(
                Document(
                    page_content=normalized_text,
                    metadata=dict(document.metadata or {}),
                )
            )

        return normalized_documents

    def _run_page_ocr(
        self,
        pdf_path: Path,
        page_number: int,
    ) -> Document:

        options = self.ocr_options

        if self.ocr_engine == "easyocr":
            result = ocr_client.easyocr_pdf_page(
                pdf_path,
                page_number=page_number,
                dpi=options.get("dpi"),
            )

        elif self.ocr_engine == "tesseract":
            result = ocr_client.tesseract_pdf_page(
                pdf_path,
                page_number=page_number,
                dpi=options.get("dpi"),
                language=options.get("language", "eng"),
                config=options.get("config", "--psm 3"),
            )

        else:
            result = ocr_client.fastocr_pdf_page(
                pdf_path,
                page_number=page_number,
                dpi=options.get("dpi"),
                languages=options.get("languages", "en"),
            )

        # EasyOCR/Tesseract return Document.
        # FastOCR currently returns list[Document].
        if isinstance(result, Document):
            return result

        if isinstance(result, list):
            text = "\n".join(
                item.page_content.strip()
                for item in result
                if item.page_content and item.page_content.strip()
            )

            metadata = dict(result[0].metadata or {}) if result else {}

            if len(result) > 1:
                metadata["ocr_document_count"] = len(result)

            return Document(
                page_content=text,
                metadata=metadata,
            )

        raise TypeError(
            f"{self.ocr_engine} returned {type(result).__name__}; "
            "expected Document or list[Document]."
        )

    def load_pdf(self, pdf_path: str | Path) -> list[Document]:
        """
        Load a PDF and return one normalized Document per page.
        """
        path = Path(pdf_path).expanduser().resolve()

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"PDF file does not exist: {path}")

        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")

        # First pass: native extraction of the entire PDF.
        native_documents = native_client.load_pdf(path)

        final_documents: list[Document] = []

        for page_index, native_document in enumerate(native_documents):

            page_number = page_index + 1
            native_text = native_document.page_content or ""
            native_length = self._text_length(native_document)

            if native_length < self.text_threshold:

                # OCR only the page with insufficient native text.
                ocr_document = self._run_page_ocr(
                    path,
                    page_number,
                )

                metadata = dict(native_document.metadata or {})
                metadata.update(dict(ocr_document.metadata or {}))

                metadata.update({
                    "source": str(path),
                    "page": page_number,
                    "extraction_method": self.ocr_engine,
                    "native_text_length": native_length,
                    "ocr_used": True,
                })

                final_documents.append(
                    Document(
                        page_content=ocr_document.page_content or "",
                        metadata=metadata,
                    )
                )

            else:

                metadata = dict(native_document.metadata or {})

                metadata.update({
                    "source": str(path),
                    "page": page_number,
                    "extraction_method": "pymupdf",
                    "native_text_length": native_length,
                    "ocr_used": False,
                })

                final_documents.append(
                    Document(
                        page_content=native_text,
                        metadata=metadata,
                    )
                )

        # Normalize only after native/OCR extraction is complete.
        return self._normalize_documents(final_documents)

    def load(self, pdf_path: str | Path) -> list[Document]:
        """Loader-style alias for load_pdf()."""
        return self.load_pdf(pdf_path)


# Reusable orchestrator instance.
pdf_loader = PDFLoader(
    text_threshold=100,
    ocr_engine="easyocr",
)


if __name__ == "__main__":

    loader = PDFLoader(
        text_threshold=100,
        ocr_engine="easyocr",
    )

    pdf_path = r"C:\Users\miyas\Downloads\organized.pdf"

    documents = loader.load(pdf_path)

    for doc in documents:
        print(
            f"Page {doc.metadata.get('page')}: "
            f"{len(doc.page_content)} characters"
        )
        print(doc)
        print("-" * 80)
