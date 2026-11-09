from pathlib import Path

import pymupdf
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.pdf_reader import ocr as ocr_module
from app.rag.pdf_reader.ocr import OCRClient


def test_fastocr_partial_result_marks_unprocessed_source_pages(monkeypatch, tmp_path):
    source_pdf = tmp_path / "partial-source.pdf"
    with pymupdf.open() as source:
        source.new_page()
        source.new_page()
        source.save(str(source_pdf))

    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_API_KEY", "gateway-client-secret")
    monkeypatch.setattr(settings, "FASTOCR_GATEWAY_BASE_URL", "http://127.0.0.1:8090")

    class FakeFastOCRLoader:
        def __init__(self, **kwargs):
            self.file_path = Path(kwargs["file_path"])

        def load(self):
            output_pdf = self.file_path.with_name(
                f"{self.file_path.stem}.searchable.pdf"
            )
            with pymupdf.open() as searchable:
                for text in ("OCR processed page", "unprocessed placeholder"):
                    page = searchable.new_page()
                    page.insert_text((72, 72), text)
                searchable.save(str(output_pdf))
            return [
                Document(
                    page_content="partial",
                    metadata={
                        "searchable_pdf_path": str(output_pdf),
                        "status": "partial",
                        "pages_billed": 1,
                    },
                )
            ]

    monkeypatch.setattr(ocr_module, "GatewayFastOCRLoader", FakeFastOCRLoader)

    documents = OCRClient(process_timeout=123).fastocr_pdf_pages(source_pdf, [1, 2])

    assert documents[1].page_content.strip() == "OCR processed page"
    assert documents[2].page_content == ""
    assert documents[2].metadata["ocr_missing_from_partial_result"] is True
