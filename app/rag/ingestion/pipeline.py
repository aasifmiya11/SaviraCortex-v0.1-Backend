"""
PDF ingestion orchestration.

Flow:
    PDF path
      -> native-first PDF loader (EasyOCR fallback)
      -> RecursiveCharacterTextSplitter
      -> Qdrant vector store

The PDF loader, splitter, embedding model, and Qdrant client are imported
as existing module-level instances. This module does not recreate them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4
import sys

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    
from langchain_core.documents import Document

from app.rag.pdf_reader.loader import pdf_loader
from app.rag.splitters.recurrsive_text_splitter import text_splitter
from app.rag.vector_stores.qdrant import client as qdrant_client

class IngestionPipeline:
    """Coordinate PDF extraction, chunking, and Qdrant insertion."""

    def __init__(self) -> None:
        # Reuse the existing singleton components.
        self.pdf_loader = pdf_loader
        self.text_splitter = text_splitter
        self.vector_store = qdrant_client

    def ingest_pdf(
        self,
        pdf_path: str | Path,
        source_filename: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Ingest a PDF and return ingestion statistics.

        Args:
            pdf_path: Existing local PDF path.
            source_filename: Original uploaded filename. This is stored in
                metadata instead of the temporary server-side file path.
            document_id: Optional stable ID. A UUID is generated if omitted.
        """
        path = Path(pdf_path).expanduser().resolve()

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"PDF file does not exist: {path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")

        document_id = document_id or str(uuid4())
        source_filename = source_filename or path.name

        # 1. Extract one Document per PDF page. OCR fallback is handled
        # internally by the existing pdf_loader.
        page_documents = self.pdf_loader.load_pdf(path)

        if not page_documents:
            raise ValueError("No pages or extractable content were found in the PDF.")

        # 2. Attach stable document-level metadata before splitting.
        for page_number, page_document in enumerate(page_documents, start=1):
            page_document.metadata.update({
                "document_id": document_id,
                "source": source_filename,
                "page": page_document.metadata.get("page", page_number),
            })

        # 3. Split page Documents. Splitter preserves page metadata and adds
        # start_index to each resulting chunk.
        chunks = self.text_splitter.split_documents(page_documents)

        # Remove empty chunks and attach chunk-level metadata.
        chunks = [
            chunk for chunk in chunks
            if chunk.page_content and chunk.page_content.strip()
        ]

        if not chunks:
            raise ValueError(
                "The PDF was loaded, but no non-empty text chunks were produced."
            )

        for chunk_index, chunk in enumerate(chunks):
            chunk.metadata.update({
                "document_id": document_id,
                "source": source_filename,
                "chunk_index": chunk_index,
            })

        # 4. Embed and persist through the existing Qdrant wrapper.
        point_ids = self.vector_store.add_documents(chunks)

        ocr_page_count = sum(
            1 for doc in page_documents
            if doc.metadata.get("ocr_used") is True
        )

        return {
            "document_id": document_id,
            "source": source_filename,
            "page_count": len(page_documents),
            "ocr_page_count": ocr_page_count,
            "chunk_count": len(chunks),
            "stored_point_count": len(point_ids) if point_ids is not None else len(chunks),
            "point_ids": point_ids,
            "status": "completed",
        }


# Reusable pipeline instance. Imported component instances are reused.
ingestion_pipeline = IngestionPipeline()


if __name__ == "__main__":
    # Example usage
    pipeline = IngestionPipeline()
    pdf_path = r"C:\Users\miyas\Downloads\organized.pdf"
    result = pipeline.ingest_pdf(pdf_path)
    print(result)