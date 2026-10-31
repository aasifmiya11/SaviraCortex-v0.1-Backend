
"""
PDF ingestion orchestration.

Flow:
    PDF path
      -> Native-first PDF loader (EasyOCR fallback)
      -> RecursiveCharacterTextSplitter
      -> Qdrant dense vector indexing
      -> BM25 sparse indexing

Existing singleton instances are reused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4
import sys

project_root = Path(__file__).resolve().parents[3]

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ..pdf_reader.loader import pdf_loader
from ..splitters.recurrsive_text_splitter import text_splitter

from ..vector_stores.qdrant import client as qdrant_client
from ..vector_stores.bm25 import bm25_client


class IngestionPipeline:
    """Coordinate PDF extraction, chunking, and indexing."""

    def __init__(self) -> None:

        # Reuse existing singleton components.
        self.pdf_loader = pdf_loader
        self.text_splitter = text_splitter

        self.qdrant_store = qdrant_client
        self.bm25_store = bm25_client

    def ingest_pdf(
        self,
        pdf_path: str | Path,
        source_filename: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:

        path = Path(pdf_path).expanduser().resolve()

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(
                f"PDF file does not exist: {path}"
            )

        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")

        document_id = document_id or str(uuid4())
        source_filename = source_filename or path.name

        # 1. Extract PDF pages.
        page_documents = self.pdf_loader.load_pdf(path)

        if not page_documents:
            raise ValueError(
                "No pages or extractable content were found in the PDF."
            )

        # 2. Attach document-level metadata.
        for page_number, page_document in enumerate(
            page_documents, start=1
        ):
            page_document.metadata.update({
                "document_id": document_id,
                "source": source_filename,
                "page": page_document.metadata.get(
                    "page", page_number
                ),
            })

        # 3. Split pages into chunks.
        chunks = self.text_splitter.split_documents(page_documents)

        chunks = [
            chunk
            for chunk in chunks
            if chunk.page_content and chunk.page_content.strip()
        ]

        if not chunks:
            raise ValueError(
                "The PDF was loaded, but no non-empty text chunks were produced."
            )

        # 4. Attach chunk-level metadata.
        for chunk_index, chunk in enumerate(chunks):
            chunk.metadata.update({
                "document_id": document_id,
                "source": source_filename,
                "chunk_index": chunk_index,
            })

        # 5. Dense indexing in Qdrant.
        point_ids = self.qdrant_store.add_documents(chunks)

        # 6. Sparse indexing in BM25.
        bm25_chunk_ids = self.bm25_store.add_documents(chunks)

        # 7. Calculate ingestion statistics.
        ocr_page_count = sum(
            1
            for doc in page_documents
            if doc.metadata.get("ocr_used") is True
        )

        return {
            "document_id": document_id,
            "source": source_filename,
            "page_count": len(page_documents),
            "ocr_page_count": ocr_page_count,
            "chunk_count": len(chunks),

            "qdrant": {
                "indexed_chunks": (
                    len(point_ids)
                    if point_ids is not None
                    else len(chunks)
                ),
                "point_ids": point_ids,
            },

            "bm25": {
                "indexed_chunks": len(bm25_chunk_ids),
                "total_indexed_chunks": self.bm25_store.count(),
            },

            "status": "completed",
        }


# Reusable pipeline instance.
ingestion_pipeline = IngestionPipeline()


if __name__ == "__main__":

    pipeline = IngestionPipeline()

    pdf_path = r"C:\Users\miyas\Downloads\organized.pdf"

    result = pipeline.ingest_pdf(pdf_path)

    print(result)
