"""Native-first PDF extraction with configurable page-level OCR fallback."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from .native import native_client
from .ocr import ocr_client
from ..ingestion.text_normalizer import TextNormalizer
from ...core.config import settings


class PDFLoader:
    """Extract native text first and send selected pages to the FastOCR API."""

    OCR_ENGINE = "fastocr"

    def __init__(
        self,
        text_threshold: int | None = None,
        *,
        ocr_all_pages: bool | None = None,
        merge_with_native: bool | None = None,
    ) -> None:
        threshold = (
            settings.MIN_NATIVE_CHARS
            if text_threshold is None
            else text_threshold
        )

        if isinstance(threshold, bool) or not isinstance(threshold, int):
            raise TypeError("text_threshold must be an integer.")
        if threshold < 0:
            raise ValueError("text_threshold cannot be negative.")

        self.text_threshold = threshold
        self.ocr_engine = self.OCR_ENGINE
        self.ocr_all_pages = (
            settings.OCR_ALL_PAGES
            if ocr_all_pages is None
            else ocr_all_pages
        )
        self.merge_with_native = (
            settings.OCR_MERGE_WITH_NATIVE
            if merge_with_native is None
            else merge_with_native
        )

        if not isinstance(self.ocr_all_pages, bool):
            raise TypeError("ocr_all_pages must be a boolean.")
        if not isinstance(self.merge_with_native, bool):
            raise TypeError("merge_with_native must be a boolean.")

    @staticmethod
    def _text_length(text: str | Document) -> int:
        value = text.page_content if isinstance(text, Document) else text
        return len("".join((value or "").split()))

    @staticmethod
    def _normalize_documents(documents: list[Document]) -> list[Document]:
        return [
            Document(
                page_content=TextNormalizer.normalize(document.page_content or ""),
                metadata=dict(document.metadata or {}),
            )
            for document in documents
        ]

    @staticmethod
    def _merge_text(native_text: str, ocr_text: str) -> str:
        native = (native_text or "").strip()
        ocr = (ocr_text or "").strip()
        if not native:
            return ocr
        if not ocr:
            return native

        native_key = " ".join(native.casefold().split())
        ocr_key = " ".join(ocr.casefold().split())
        if native_key in ocr_key:
            return ocr
        if ocr_key in native_key:
            return native
        return f"{native}\n\n{ocr}"

    @staticmethod
    def _mean_ocr_confidence(metadata: dict[str, Any]) -> float | None:
        configured_mean = metadata.get("mean_confidence")
        if (
            isinstance(configured_mean, (int, float))
            and not isinstance(configured_mean, bool)
            and 0.0 <= float(configured_mean) <= 1.0
        ):
            return float(configured_mean)

        detections = metadata.get("detections")
        if not isinstance(detections, list):
            return None
        values = [
            float(item["confidence"])
            for item in detections
            if isinstance(item, dict)
            and isinstance(item.get("confidence"), (int, float))
            and not isinstance(item.get("confidence"), bool)
            and 0.0 <= float(item["confidence"]) <= 1.0
        ]
        return sum(values) / len(values) if values else None

    @classmethod
    def _ocr_is_usable(
        cls,
        native_text: str,
        ocr_text: str,
        ocr_metadata: dict[str, Any],
    ) -> bool:
        if cls._text_length(ocr_text) == 0:
            return False
        if cls._text_length(native_text) == 0:
            return True
        confidence = cls._mean_ocr_confidence(ocr_metadata)
        return confidence is None or confidence >= 0.5

    @classmethod
    def _ocr_is_better(
        cls,
        native_text: str,
        ocr_text: str,
        ocr_metadata: dict[str, Any],
    ) -> bool:
        native_length = cls._text_length(native_text)
        ocr_length = cls._text_length(ocr_text)
        return (
            ocr_length > native_length
            and cls._ocr_is_usable(native_text, ocr_text, ocr_metadata)
        )

    def _run_pages_ocr(
        self, pdf_path: Path, page_numbers: list[int]
    ) -> dict[int, Document]:
        result = ocr_client.fastocr_pdf_pages(pdf_path, page_numbers)
        if not isinstance(result, dict) or any(
            not isinstance(page, int) or not isinstance(document, Document)
            for page, document in result.items()
        ):
            raise TypeError("FastOCR must return a dict[int, Document].")
        return result

    def load_pdf(self, pdf_path: str | Path) -> list[Document]:
        path = Path(pdf_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"PDF file does not exist: {path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")

        native_documents = native_client.load_pdf(path)
        pages_to_ocr = [
            page_index + 1
            for page_index, native_document in enumerate(native_documents)
            if self.ocr_all_pages
            or self._text_length(native_document.page_content or "") < self.text_threshold
        ]

        ocr_results: dict[int, Document] = {}
        if pages_to_ocr:
            from app.services.document_ingestion.batch_config import OCR_SLOTS

            # One FastOCR document per source PDF, containing only pages that
            # need OCR. This respects the provider's document concurrency cap.
            with OCR_SLOTS:
                ocr_results = self._run_pages_ocr(path, pages_to_ocr)

        final_documents: list[Document] = []
        for page_index, native_document in enumerate(native_documents):
            page_number = page_index + 1
            native_text = native_document.page_content or ""
            native_length = self._text_length(native_text)
            should_ocr = page_number in pages_to_ocr

            metadata = dict(native_document.metadata or {})
            metadata.update({
                "source": str(path),
                "page": page_number,
                "native_text_length": native_length,
                "ocr_attempted": should_ocr,
                "ocr_used": False,
            })

            final_text = native_text
            if should_ocr:
                ocr_document = ocr_results.get(page_number)
                if ocr_document is None:
                    metadata.update({
                        "ocr_text_length": 0,
                        "ocr_mean_confidence": None,
                        "ocr_missing_from_partial_result": True,
                        "extraction_method": "pymupdf",
                    })
                else:
                    ocr_text = ocr_document.page_content or ""
                    ocr_length = self._text_length(ocr_text)
                    ocr_metadata = dict(ocr_document.metadata or {})
                    metadata.update(ocr_metadata)
                    metadata.update({
                        "source": str(path),
                        "page": page_number,
                        "native_text_length": native_length,
                        "ocr_text_length": ocr_length,
                        "ocr_attempted": True,
                    })

                    confidence = self._mean_ocr_confidence(ocr_metadata)
                    metadata["ocr_mean_confidence"] = confidence
                    ocr_is_better = self._ocr_is_better(
                        native_text,
                        ocr_text,
                        ocr_metadata,
                    )
                    ocr_usable = self._ocr_is_usable(
                        native_text,
                        ocr_text,
                        ocr_metadata,
                    )

                    if (
                        self.merge_with_native
                        and ocr_usable
                        and not (
                            ocr_is_better
                            and self._text_length(native_text) < 10
                        )
                        and (
                            ocr_is_better
                            or confidence is not None
                        )
                    ):
                        final_text = self._merge_text(native_text, ocr_text)
                        ocr_contributed = final_text != native_text
                        metadata["extraction_method"] = (
                            f"pymupdf+{self.ocr_engine}"
                            if ocr_contributed
                            else "pymupdf"
                        )
                    elif ocr_is_better:
                        final_text = ocr_text
                        ocr_contributed = True
                        metadata["extraction_method"] = self.ocr_engine
                    else:
                        ocr_contributed = False
                        metadata["extraction_method"] = "pymupdf"

                    metadata["ocr_used"] = ocr_contributed
            else:
                metadata["extraction_method"] = "pymupdf"

            final_documents.append(
                Document(page_content=final_text, metadata=metadata)
            )

        return self._normalize_documents(final_documents)

    def load(self, pdf_path: str | Path) -> list[Document]:
        return self.load_pdf(pdf_path)


pdf_loader = PDFLoader()


if __name__ == "__main__":
    from rich import print

    pdf_path = r"C:\Users\miyas\Downloads\organized.pdf"
    documents = pdf_loader.load(pdf_path)
    for document in documents:
        print(
            f"Page {document.metadata.get('page')}: "
            f"{len(document.page_content)} characters"
        )
        print(document)
        print("-" * 80)
