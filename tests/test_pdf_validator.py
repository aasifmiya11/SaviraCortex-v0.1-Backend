
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.pdf_reader.validator import PDFValidator


def main():
    parser = argparse.ArgumentParser(
        description="Test PDF validation."
    )

    parser.add_argument(
        "file_path",
        help="Path to the PDF file to validate.",
    )

    args = parser.parse_args()

    validator = PDFValidator(
        max_file_size_mb=100,
        max_pages=2000,
    )

    result = validator.validate(args.file_path)

    print("\n========== PDF VALIDATION ==========")

    print("Valid:", result.is_valid)
    print("File:", result.file_path)
    print("Size:", f"{result.file_size:,} bytes")
    print("Pages:", result.page_count)

    if result.warnings:
        print("\nWarnings:")
        for warning in result.warnings:
            print(f"  [WARNING] {warning}")

    if result.errors:
        print("\nErrors:")
        for error in result.errors:
            print(f"  [ERROR] {error}")

    if result.is_valid:
        print("\nPDF validation successful.")
    else:
        print("\nPDF validation failed.")

    print("====================================")

    return 0 if result.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
