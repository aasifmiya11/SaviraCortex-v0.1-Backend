import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.pdf_reader import loader as loader_module
from app.rag.pdf_reader.loader import PDFLoader


def _load_page(monkeypatch, tmp_path, native_text, ocr_text, *, ocr_metadata=None, **kwargs):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        loader_module.native_client,
        "load_pdf",
        lambda _path: [
            Document(page_content=native_text, metadata={"page": 0})
        ],
    )
    monkeypatch.setattr(
        loader_module.ocr_client,
        "fastocr_pdf_pages",
        lambda _path, page_numbers: {
            page_number: Document(
                page_content=ocr_text,
                metadata=dict(ocr_metadata or {}),
            )
            for page_number in page_numbers
        },
    )

    loader = PDFLoader(
        text_threshold=100,
        **kwargs,
    )
    return loader.load_pdf(pdf_path)[0]


def test_empty_ocr_preserves_native_text(monkeypatch, tmp_path):
    page = _load_page(
        monkeypatch, tmp_path, "native text", "   "
    )
    assert page.page_content == "native text"
    assert page.metadata["ocr_attempted"] is True
    assert page.metadata["ocr_used"] is False
    assert page.metadata["extraction_method"] == "pymupdf"


def test_shorter_ocr_preserves_native_text(monkeypatch, tmp_path):
    page = _load_page(
        monkeypatch, tmp_path, "native extraction has useful text", "ocr"
    )
    assert page.page_content == "native extraction has useful text"
    assert page.metadata["ocr_used"] is False


def test_low_confidence_ocr_does_not_replace_native_text(monkeypatch, tmp_path):
    page = _load_page(
        monkeypatch,
        tmp_path,
        "native extraction",
        "a longer but probably incorrect OCR output",
        ocr_metadata={"mean_confidence": 0.31},
    )
    assert page.page_content == "native extraction"
    assert page.metadata["ocr_used"] is False
    assert page.metadata["ocr_mean_confidence"] == pytest.approx(0.31)


def test_better_ocr_replaces_insufficient_native_text(monkeypatch, tmp_path):
    page = _load_page(
        monkeypatch,
        tmp_path,
        "short",
        "a much longer OCR transcription with reliable content",
        ocr_metadata={"mean_confidence": 0.91},
    )
    assert page.page_content.startswith("a much longer OCR transcription")
    assert page.metadata["ocr_used"] is True
    assert page.metadata["extraction_method"] == "fastocr"


def test_merge_setting_combines_distinct_native_and_ocr_text(monkeypatch, tmp_path):
    page = _load_page(
        monkeypatch,
        tmp_path,
        "native paragraph",
        "additional OCR paragraph",
        ocr_metadata={"mean_confidence": 0.9},
        merge_with_native=True,
    )
    assert "native paragraph" in page.page_content
    assert "additional OCR paragraph" in page.page_content
    assert page.metadata["extraction_method"] == "pymupdf+fastocr"


def test_ocr_all_pages_forces_attempt_even_when_native_text_is_long(monkeypatch, tmp_path):
    page = _load_page(
        monkeypatch,
        tmp_path,
        "native text " * 30,
        "small OCR result",
        ocr_all_pages=True,
    )
    assert page.metadata["ocr_attempted"] is True
    assert page.metadata["ocr_used"] is False
    assert page.metadata["page"] == 1


def test_loader_defaults_are_wired_to_settings(monkeypatch):
    monkeypatch.setattr(settings, "MIN_NATIVE_CHARS", 77)
    monkeypatch.setattr(settings, "OCR_ALL_PAGES", True)
    monkeypatch.setattr(settings, "OCR_MERGE_WITH_NATIVE", True)

    loader = PDFLoader()

    assert loader.text_threshold == 77
    assert loader.ocr_engine == "fastocr"
    assert loader.ocr_all_pages is True
    assert loader.merge_with_native is True


def test_merge_setting_keeps_shorter_high_confidence_ocr_text(monkeypatch, tmp_path):
    page = _load_page(
        monkeypatch,
        tmp_path,
        "native paragraph with substantial text",
        "small table",
        ocr_metadata={"mean_confidence": 0.96},
        merge_with_native=True,
    )
    assert "native paragraph with substantial text" in page.page_content
    assert "small table" in page.page_content
    assert page.metadata["ocr_used"] is True


def test_selected_pages_are_submitted_as_one_batch(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    native_pages = [
        Document(page_content="This native page has enough useful text.", metadata={}),
        Document(page_content="", metadata={}),
        Document(page_content="Another native page with enough useful text.", metadata={}),
        Document(page_content="tiny", metadata={}),
    ]
    calls = []

    monkeypatch.setattr(
        loader_module.native_client,
        "load_pdf",
        lambda _path: native_pages,
    )

    def fake_fastocr(_path, page_numbers):
        calls.append(list(page_numbers))
        return {
            2: Document(page_content="OCR text for source page two", metadata={}),
            4: Document(page_content="OCR text for source page four", metadata={}),
        }

    monkeypatch.setattr(loader_module.ocr_client, "fastocr_pdf_pages", fake_fastocr)

    documents = PDFLoader(text_threshold=10).load_pdf(pdf_path)

    assert calls == [[2, 4]]
    assert [document.metadata["page"] for document in documents] == [1, 2, 3, 4]
    assert documents[1].page_content == "OCR text for source page two"
    assert documents[3].page_content == "OCR text for source page four"
    assert documents[0].metadata["ocr_attempted"] is False
    assert documents[2].metadata["ocr_attempted"] is False
