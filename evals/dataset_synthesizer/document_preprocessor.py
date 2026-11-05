"""Prepare temporary Markdown inputs using SaviraCortex's PDF pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.rag.pdf_reader.loader import pdf_loader


def prepare_markdown_documents(
    pdf_paths: Iterable[str | Path],
    temporary_directory: str | Path,
) -> tuple[list[Path], list[dict[str, str | int]]]:
    """Extract and normalize PDFs, then write one temporary Markdown per PDF.

    PDFLoader already applies TextNormalizer and preserves page metadata.
    This runs before the application's own chunking/indexing stage.
    """
    output_dir = Path(temporary_directory)
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_paths: list[Path] = []
    source_manifest: list[dict[str, str | int]] = []
    resolved_pdf_paths = [Path(path).expanduser().resolve() for path in pdf_paths]
    if not resolved_pdf_paths:
        raise ValueError("At least one source PDF must be provided.")

    for document_index, pdf_path in enumerate(resolved_pdf_paths, start=1):
        if not pdf_path.is_file():
            raise FileNotFoundError(f"Source PDF does not exist: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file, received: {pdf_path}")

        # Reuse the same native-text/OCR and normalization path as ingestion.
        documents = pdf_loader.load_pdf(pdf_path)
        if not documents:
            raise ValueError(f"No pages were extracted from {pdf_path.name}.")

        sections = [f"# {pdf_path.stem}\n"]
        non_empty_pages = 0

        for fallback_page, document in enumerate(documents, start=1):
            page_number = document.metadata.get("page", fallback_page)
            page_text = (document.page_content or "").strip()
            if not page_text:
                continue
            non_empty_pages += 1
            sections.append(f"## Page {page_number}\n\n{page_text}\n")

        if non_empty_pages == 0:
            raise ValueError(
                f"PDF extraction produced no non-empty page content: {pdf_path}"
            )

        markdown_path = output_dir / f"{document_index:04d}_{pdf_path.stem}.md"
        markdown_path.write_text("\n".join(sections), encoding="utf-8")
        markdown_paths.append(markdown_path)
        source_manifest.append(
            {
                "source_pdf": str(pdf_path),
                "page_count": len(documents),
                "non_empty_page_count": non_empty_pages,
            }
        )

    return markdown_paths, source_manifest
