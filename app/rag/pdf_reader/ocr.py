"""FastOCR adapter routed through the SaviraCortex provider gateway."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf
from langchain_core.documents import Document
from fastocr_sdk import FastOCR
from fastocr_sdk.errors import RateLimitError
from langchain_fastocr import FastOCRLoader

from ...core.config import settings


class GatewayFastOCRLoader(FastOCRLoader):
    """FastOCRLoader with one SDK retry before account-level concurrency fallback."""

    def _client(self) -> FastOCR:
        return FastOCR(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=1,
        )


class OCRClient:
    """Batch selected PDF pages through FastOCR without exposing provider keys."""

    SUPPORTED_IMAGE_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"
    }

    def __init__(self, process_timeout: float | None = None) -> None:
        self.gateway_api_key = settings.FASTOCR_GATEWAY_API_KEY
        self.gateway_base_url = settings.FASTOCR_GATEWAY_BASE_URL
        self.process_timeout = (
            settings.FASTOCR_PROCESS_TIMEOUT_SECONDS
            if process_timeout is None
            else process_timeout
        )

    @staticmethod
    def _validate_file(file_path: str | Path) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Expected a file path: {path}")
        return path

    def _run_fastocr(
        self,
        file_path: str | Path,
        *,
        output: str = "text",
    ) -> list[Document]:
        if not self.gateway_api_key:
            raise ValueError(
                "FASTOCR_GATEWAY_API_KEY (or the JINA_API_KEY fallback) is not configured."
            )

        path = self._validate_file(file_path)
        loader = GatewayFastOCRLoader(
            file_path=str(path),
            api_key=self.gateway_api_key,
            base_url=self.gateway_base_url,
            output=output,
            timeout=self.process_timeout,
        )
        return loader.load()

    def fastocr_pdf_pages(
        self,
        pdf_path: str | Path,
        page_numbers: list[int],
    ) -> dict[int, Document]:
        """Send only selected pages as one temporary PDF and restore page numbers."""
        path = self._validate_file(pdf_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")

        if any(
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or page_number < 1
            for page_number in page_numbers
        ):
            raise ValueError("page_numbers must contain positive 1-indexed integers.")
        selected_pages = sorted(set(page_numbers))
        if not selected_pages:
            return {}

        with tempfile.TemporaryDirectory(prefix="fastocr_selected_pages_") as temp_dir:
            temp_root = Path(temp_dir)
            selected_pdf_path = temp_root / "selected_pages.pdf"

            with pymupdf.open(str(path)) as source, pymupdf.open() as selected:
                if any(page_number > len(source) for page_number in selected_pages):
                    raise ValueError(
                        f"page_numbers must be between 1 and {len(source)}."
                    )
                for page_number in selected_pages:
                    selected.insert_pdf(
                        source,
                        from_page=page_number - 1,
                        to_page=page_number - 1,
                    )
                selected.save(str(selected_pdf_path), garbage=4, deflate=True)

            account_fallbacks = 0
            while True:
                try:
                    loaded_docs = self._run_fastocr(
                        selected_pdf_path,
                        output="pdf",
                    )
                    break
                except RateLimitError as exc:
                    if (
                        exc.code != "concurrency_limit"
                        or account_fallbacks >= settings.FASTOCR_MAX_ACCOUNT_FALLBACKS
                    ):
                        raise
                    # FastOCR leaves a concurrency-rejected document awaiting
                    # upload/start. Re-submit the original selected-page PDF;
                    # the gateway has cooled down that account and will choose
                    # the next eligible account for this new document.
                    account_fallbacks += 1

            if not loaded_docs:
                raise RuntimeError("FastOCR returned no document result.")
            for loaded_doc in loaded_docs:
                loaded_doc.metadata["fastocr_account_fallbacks"] = account_fallbacks

            result_metadata = dict(loaded_docs[0].metadata or {})
            searchable_pdf_value = result_metadata.get("searchable_pdf_path")
            if not searchable_pdf_value:
                raise RuntimeError(
                    "FastOCR did not return a searchable PDF needed to map OCR text to source pages."
                )
            searchable_pdf_path = Path(searchable_pdf_value)
            if not searchable_pdf_path.is_file():
                raise FileNotFoundError(
                    f"FastOCR searchable PDF was not found: {searchable_pdf_path}"
                )

            documents: dict[int, Document] = {}
            with pymupdf.open(str(searchable_pdf_path)) as searchable_pdf:
                try:
                    pages_billed = int(result_metadata.get("pages_billed"))
                except (TypeError, ValueError):
                    pages_billed = len(searchable_pdf)
                processed_page_count = min(len(searchable_pdf), pages_billed)
                for index, original_page_number in enumerate(selected_pages):
                    page_was_processed = index < processed_page_count
                    text = (
                        searchable_pdf[index].get_text("text")
                        if page_was_processed
                        else ""
                    )
                    metadata = {
                        key: value
                        for key, value in result_metadata.items()
                        if key not in {"source", "file_name", "searchable_pdf_path"}
                    }
                    metadata.update({
                        "source": str(path),
                        "page": original_page_number,
                        "engine": "fastocr",
                        "ocr_batch_page_index": index + 1,
                        "ocr_batch_page_count": len(selected_pages),
                    })
                    if not page_was_processed:
                        metadata["ocr_missing_from_partial_result"] = True
                    documents[original_page_number] = Document(
                        page_content=text,
                        metadata=metadata,
                    )
            return documents

    def fastocr_pdf(self, pdf_path: str | Path) -> list[Document]:
        path = self._validate_file(pdf_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")
        with pymupdf.open(str(path)) as pdf:
            page_numbers = list(range(1, len(pdf) + 1))
        return list(self.fastocr_pdf_pages(path, page_numbers).values())

    def fastocr_image(self, image_path: str | Path) -> list[Document]:
        path = self._validate_file(image_path)
        if path.suffix.lower() not in self.SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image format: {path.suffix}")
        return self._run_fastocr(path)


ocr_client = OCRClient(
    process_timeout=settings.FASTOCR_PROCESS_TIMEOUT_SECONDS
)
