from uuid import uuid4
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.ingestion.text_normalizer import TextNormalizer


def test_normalize():
    raw_text = (
        "  EMPLOYEE POLICY   \r\n"
        "\r\n"
        "This   is   a sample paragraph.\x00\r\n"
        "\r\n"
        "\r\n"
        "Section 1:\tLeave Policy\r\n"
        "Employees are entitled to annual leave."
    )

    normalized = TextNormalizer.normalize(raw_text)

    print("\nNORMALIZED TEXT")
    print("=" * 60)
    print(normalized)

    assert "\x00" not in normalized
    assert "\r" not in normalized
    assert "EMPLOYEE POLICY" in normalized
    assert "Section 1:" in normalized
    assert "Leave Policy" in normalized
    assert "This is a sample paragraph." in normalized

    print("\nBasic normalization test passed.")


def test_normalize_pages():
    pages = [
        "  First page text.   ",
        "Second page text.\x00",
        "Third page text.",
    ]

    normalized_pages = TextNormalizer.normalize_pages(pages)

    assert len(normalized_pages) == 3
    assert normalized_pages[0] == "First page text."
    assert normalized_pages[1] == "Second page text."

    combined = TextNormalizer.combine_pages(pages)

    assert "[PAGE 1]" in combined
    assert "[PAGE 2]" in combined
    assert "[PAGE 3]" in combined

    print("\nPAGE NORMALIZATION")
    print("=" * 60)
    print(combined)

    print("\nPage normalization test passed.")


if __name__ == "__main__":
    test_normalize()
    test_normalize_pages()

    print("\nAll tests passed.")