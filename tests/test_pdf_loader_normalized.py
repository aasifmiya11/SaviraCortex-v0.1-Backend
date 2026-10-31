import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import sys
from pathlib import Path

from app.rag.pdf_reader.loader import PDFLoader


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: py scripts/test_pdf_loader_normalized.py <pdf_path>"
        )
        return

    pdf_path = Path(sys.argv[1])

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return

    loader = PDFLoader(
        text_threshold=100,
        ocr_engine="easyocr",
    )

    documents = loader.load_pdf(pdf_path)

    print("\nPDF LOADER + NORMALIZER TEST")
    print("=" * 70)

    print(f"PDF: {pdf_path.name}")
    print(f"Total pages extracted: {len(documents)}")

    assert len(documents) > 0, "No pages were extracted."

    for expected_page, document in enumerate(documents, start=1):

        text = document.page_content
        metadata = document.metadata

        assert isinstance(text, str)
        assert metadata.get("page") == expected_page
        assert "\x00" not in text
        assert "\r" not in text

        print(f"\nPage: {metadata.get('page')}")
        print(f"Extraction: {metadata.get('extraction_method')}")
        print(f"OCR used: {metadata.get('ocr_used')}")
        print(f"Native characters: {metadata.get('native_text_length')}")
        print(f"Normalized characters: {len(text)}")

        print("\nText preview:")
        print(text[:500] if text else "[No text extracted]")

        print("-" * 70)

    print("\nAll PDF loader and normalizer checks passed.")


if __name__ == "__main__":
    main()
