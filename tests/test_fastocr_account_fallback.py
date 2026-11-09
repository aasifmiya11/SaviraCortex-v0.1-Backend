from pathlib import Path

import pymupdf
import pytest
from fastocr_sdk.errors import DocumentFailedError, RateLimitError
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.pdf_reader import ocr as ocr_module
from app.rag.pdf_reader.ocr import OCRClient


def _one_page_pdf(path: Path) -> None:
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "source page")
        pdf.save(str(path))


def test_concurrency_limit_retries_original_selected_pdf_on_next_account(
    monkeypatch, tmp_path
):
    source_pdf = tmp_path / "source.pdf"
    _one_page_pdf(source_pdf)
    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_API_KEY", "gateway-client-secret")
    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_BASE_URL", "http://127.0.0.1:8090")
    monkeypatch.setattr(settings, "FASTOCR_MAX_ACCOUNT_FALLBACKS", 2)
    calls = []

    class FakeGatewayLoader:
        def __init__(self, **kwargs):
            self.file_path = Path(kwargs["file_path"])

        def load(self):
            calls.append(self.file_path)
            if len(calls) == 1:
                raise RateLimitError(
                    "Account already has two documents processing",
                    status_code=429,
                    code="concurrency_limit",
                    retry_after=30,
                )
            output_pdf = self.file_path.with_name(
                f"{self.file_path.stem}.searchable.pdf"
            )
            with pymupdf.open() as searchable:
                page = searchable.new_page()
                page.insert_text((72, 72), "OCR result after fallback")
                searchable.save(str(output_pdf))
            return [
                Document(
                    page_content="OCR result",
                    metadata={
                        "searchable_pdf_path": str(output_pdf),
                        "status": "completed",
                        "pages_billed": 1,
                    },
                )
            ]

    monkeypatch.setattr(
        ocr_module, "GatewayFastOCRLoader", FakeGatewayLoader
    )

    documents = OCRClient(process_timeout=123).fastocr_pdf_pages(source_pdf, [1])

    assert len(calls) == 2
    assert documents[1].page_content.strip() == "OCR result after fallback"
    assert documents[1].metadata["fastocr_account_fallbacks"] == 1


def test_monthly_page_quota_error_is_not_retried_on_another_account(
    monkeypatch, tmp_path
):
    source_pdf = tmp_path / "source.pdf"
    _one_page_pdf(source_pdf)
    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_API_KEY", "gateway-client-secret")
    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_BASE_URL", "http://127.0.0.1:8090")
    calls = []

    class OutOfPagesLoader:
        def __init__(self, **kwargs):
            self.file_path = Path(kwargs["file_path"])

        def load(self):
            calls.append(self.file_path)
            raise DocumentFailedError(
                "Monthly page allowance exhausted",
                document_id="fastocr-doc-out-of-pages",
                code="buy_pages",
                retryable=False,
            )

    monkeypatch.setattr(
        ocr_module, "GatewayFastOCRLoader", OutOfPagesLoader
    )

    with pytest.raises(DocumentFailedError) as caught:
        OCRClient(process_timeout=123).fastocr_pdf_pages(source_pdf, [1])

    assert caught.value.out_of_pages is True
    assert len(calls) == 1


def test_non_concurrency_rate_limit_does_not_reupload_existing_document(
    monkeypatch, tmp_path
):
    source_pdf = tmp_path / "source.pdf"
    _one_page_pdf(source_pdf)
    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_API_KEY", "gateway-client-secret")
    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_BASE_URL", "http://127.0.0.1:8090")
    calls = []

    class PerKeyThrottleLoader:
        def __init__(self, **kwargs):
            self.file_path = Path(kwargs["file_path"])

        def load(self):
            calls.append(self.file_path)
            raise RateLimitError(
                "Per-key request rate limit",
                status_code=429,
                retry_after=30,
            )

    monkeypatch.setattr(
        ocr_module, "GatewayFastOCRLoader", PerKeyThrottleLoader
    )

    with pytest.raises(RateLimitError):
        OCRClient(process_timeout=123).fastocr_pdf_pages(source_pdf, [1])

    assert len(calls) == 1
