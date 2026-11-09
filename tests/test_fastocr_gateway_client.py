from pathlib import Path

import pymupdf
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.pdf_reader import ocr as ocr_module
from app.rag.pdf_reader.ocr import OCRClient


def test_fastocr_batches_only_selected_pages_through_gateway(monkeypatch, tmp_path):
    source_pdf = tmp_path / "source.pdf"
    with pymupdf.open() as source:
        for page_number in range(1, 5):
            page = source.new_page()
            page.insert_text((72, 72), f"Original page {page_number}")
        source.save(str(source_pdf))

    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_API_KEY", "gateway-client-secret")
    monkeypatch.setattr(
        settings, "FASTOCR_GATEWAY_BASE_URL", "http://127.0.0.1:8090"
    )
    monkeypatch.setattr(settings, "FASTOCR_PROCESS_TIMEOUT_SECONDS", 123)

    calls = {}

    class FakeFastOCRLoader:
        def __init__(self, **kwargs):
            calls.update(kwargs)

        def load(self):
            selected_pdf = Path(calls["file_path"])
            with pymupdf.open(str(selected_pdf)) as selected:
                assert len(selected) == 2
                assert selected[0].get_text().strip() == "Original page 2"
                assert selected[1].get_text().strip() == "Original page 4"

            output_pdf = selected_pdf.with_name(
                f"{selected_pdf.stem}.searchable.pdf"
            )
            with pymupdf.open() as searchable:
                for text in ("OCR text for page two", "OCR text for page four"):
                    page = searchable.new_page()
                    page.insert_text((72, 72), text)
                searchable.save(str(output_pdf))

            return [
                Document(
                    page_content="combined OCR text",
                    metadata={
                        "searchable_pdf_path": str(output_pdf),
                        "status": "completed",
                        "pages_billed": 2,
                        "document_id": "fastocr-document-id",
                    },
                )
            ]

    monkeypatch.setattr(ocr_module, "GatewayFastOCRLoader", FakeFastOCRLoader)

    documents = OCRClient(process_timeout=123).fastocr_pdf_pages(source_pdf, [4, 2])

    assert calls["api_key"] == "gateway-client-secret"
    assert calls["base_url"] == "http://127.0.0.1:8090"
    assert calls["output"] == "pdf"
    assert calls["timeout"] == 123
    assert set(documents) == {2, 4}
    assert documents[2].page_content.strip() == "OCR text for page two"
    assert documents[4].page_content.strip() == "OCR text for page four"
    assert documents[2].metadata["page"] == 2
    assert documents[4].metadata["page"] == 4
    assert documents[2].metadata["engine"] == "fastocr"
    assert documents[4].metadata["ocr_batch_page_count"] == 2
