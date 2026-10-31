import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.ingestion.hash_service import PDFHashService


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_hash_service.py <pdf_path>")
        return

    pdf_path = Path(sys.argv[1])

    try:
        file_hash = PDFHashService.calculate_file_hash(pdf_path)

        sample_text = "This is a sample extracted and normalized PDF text."

        content_hash = PDFHashService.calculate_content_hash(sample_text)

        print("\nPDF HASH TEST")
        print("-" * 50)
        print(f"File:         {pdf_path.name}")
        print(f"File SHA-256: {file_hash}")
        print(f"Content SHA:  {content_hash}")

    except Exception as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()