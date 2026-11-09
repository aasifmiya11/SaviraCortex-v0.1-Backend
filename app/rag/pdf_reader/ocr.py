"""FastOCR API adapter; no OCR models are loaded in the backend process."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import pymupdf
from PIL import Image
from langchain_core.documents import Document
from langchain_fastocr import FastOCRLoader

from ...core.config import settings


class OCRClient:
    """Send PDF pages and images to the hosted FastOCR API."""

    SUPPORTED_IMAGE_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"
    }

    def __init__(self, default_dpi: int = 300) -> None:
        self.fastocr_api_key = getattr(settings, "FASTOCR_API_KEY", None)
        self.default_dpi = default_dpi

    @staticmethod
    def _validate_file(file_path: str | Path) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Expected a file path: {path}")
        return path

    @staticmethod
    def _validate_page_number(pdf: pymupdf.Document, page_number: int) -> None:
        if not isinstance(page_number, int) or isinstance(page_number, bool):
            raise TypeError("page_number must be an integer (1-indexed).")
        if not 1 <= page_number <= len(pdf):
            raise ValueError(
                f"page_number must be between 1 and {len(pdf)}; got {page_number}."
            )

    @staticmethod
    def _render_page(page: pymupdf.Page, dpi: int) -> Image.Image:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def _run_fastocr(
        self,
        file_path: str | Path,
        *,
        page_number: Optional[int] = None,
    ) -> list[Document]:
        if not self.fastocr_api_key:
            raise ValueError(
                "FASTOCR_API_KEY is not configured in app.core.config.settings."
            )

        path = self._validate_file(file_path)
        loader = FastOCRLoader(
            file_path=str(path),
            api_key=self.fastocr_api_key,
        )
        loaded_docs = loader.load()

        documents: list[Document] = []
        for index, loaded_doc in enumerate(loaded_docs):
            metadata = dict(loaded_doc.metadata or {})
            metadata.update({
                "source": str(path),
                "engine": "fastocr",
            })
            if page_number is not None:
                metadata["page"] = page_number
            elif "page" not in metadata:
                metadata["page"] = index + 1

            documents.append(Document(
                page_content=loaded_doc.page_content,
                metadata=metadata,
            ))
        return documents

    def fastocr_pdf(self, pdf_path: str | Path) -> list[Document]:
        """Send a complete PDF to the hosted FastOCR API."""
        path = self._validate_file(pdf_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")
        return self._run_fastocr(path)

    def fastocr_pdf_page(
        self,
        pdf_path: str | Path,
        page_number: int,
        dpi: Optional[int] = None,
    ) -> list[Document]:
        """Render one page locally, then send that image to FastOCR."""
        path = self._validate_file(pdf_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")

        with pymupdf.open(str(path)) as pdf:
            self._validate_page_number(pdf, page_number)
            image = self._render_page(pdf[page_number - 1], dpi or self.default_dpi)

        with tempfile.TemporaryDirectory(prefix="fastocr_page_") as temp_dir:
            image_path = Path(temp_dir) / f"page_{page_number}.png"
            image.save(image_path, format="PNG")
            return self._run_fastocr(image_path, page_number=page_number)

    def fastocr_image(self, image_path: str | Path) -> list[Document]:
        """Send one supported image to the hosted FastOCR API."""
        path = self._validate_file(image_path)
        if path.suffix.lower() not in self.SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image format: {path.suffix}")
        return self._run_fastocr(path)


ocr_client = OCRClient(default_dpi=settings.RENDER_DPI)
