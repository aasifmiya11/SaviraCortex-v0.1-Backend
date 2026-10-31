"""
OCRClient.py

Black-box OCR service supporting FastOCR, EasyOCR, and Tesseract.
Each engine can process an entire PDF, one PDF page (1-indexed), or an image.

The caller decides when OCR is needed. Native PDF text extraction and
threshold-based fallback belong to the document ingestion pipeline.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any, Optional, Sequence

# Add project root when executed directly.
# Expected location: <project_root>/app/.../OCRClient.py
try:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
except IndexError:
    pass

import pymupdf
import numpy as np
import easyocr
import pytesseract

from PIL import Image
from pytesseract import Output
from langchain_core.documents import Document
from langchain_fastocr import FastOCRLoader

from app.core.config import settings
from rich import print

class OCRClient:
    """
    Unified, black-box OCR interface. PDF page numbers are 1-indexed.
    ARGS:
        easyocr_languages: List of language codes for EasyOCR (default: ["en"]).
        easyocr_gpu: Whether to use GPU for EasyOCR (default: False).
        tesseract_cmd: Optional path to the Tesseract executable (default: None).
        default_dpi: Default DPI for rendering PDF pages (default: 200).
        initialize_easyocr: Whether to initialize EasyOCR on instantiation (default: True).
    
    Functions:
        easyocr_pdf(pdf_path, dpi=None) -> list[Document]
        easyocr_pdf_page(pdf_path, page_number, dpi=None) -> Document
        easyocr_image(image_path) -> Document

        tesseract_pdf(pdf_path, dpi=None, language="eng", config="--psm 3") -> list[Document]
        tesseract_pdf_page(pdf_path, page_number, dpi=None, language="eng", config="--psm 3") -> Document
        tesseract_image(image_path, language="eng", config="--psm 3") -> Document

        fastocr_pdf(pdf_path, languages="en") -> list[Document]
        fastocr_pdf_page(pdf_path, page_number, dpi=None, languages="en") -> list[Document]
        fastocr_image(image_path, languages="en") -> list[Document]
    """

    SUPPORTED_IMAGE_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"
    }

    def __init__(self,easyocr_languages: Optional[Sequence[str]] = None,easyocr_gpu: bool = False,tesseract_cmd: Optional[str] = None,default_dpi: int = 200,initialize_easyocr: bool = True,) -> None:
        self.fastocr_api_key = getattr(settings, "FASTOCR_API_KEY", None)
        self.default_dpi = default_dpi
        self.easyocr_languages = list(easyocr_languages or ["en"])
        self.easyocr_gpu = easyocr_gpu
        self.easy_reader = None

        configured_cmd = tesseract_cmd or getattr(settings, "TESSERACT_CMD", None)
        if configured_cmd:
            pytesseract.pytesseract.tesseract_cmd = str(configured_cmd)

        # Lazy initialization is also available by setting initialize_easyocr=False.
        if initialize_easyocr:
            self._initialize_easyocr()

    # -------------------------- Shared helpers --------------------------

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
    def _open_pdf(path: Path) -> pymupdf.Document:
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")
        return pymupdf.open(str(path))

    @classmethod
    def _open_image(cls, path: Path) -> Image.Image:
        if path.suffix.lower() not in cls.SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image format: {path.suffix}")
        with Image.open(path) as image:
            return image.convert("RGB").copy()

    @staticmethod
    def _render_page(page: pymupdf.Page, dpi: int) -> Image.Image:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    @staticmethod
    def _make_document(
        text: str,
        *,
        source: str,
        engine: str,
        page_number: Optional[int] = None,
        detections: Optional[list[dict[str, Any]]] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> Document:
        metadata: dict[str, Any] = {"source": source, "engine": engine}
        if page_number is not None:
            metadata["page"] = page_number
        if detections is not None:
            metadata["detections"] = detections
        if extra_metadata:
            metadata.update(extra_metadata)
        return Document(page_content=text.strip(), metadata=metadata)

    # ----------------------------- EasyOCR -----------------------------

    def _initialize_easyocr(self) -> None:
        if self.easy_reader is None:
            self.easy_reader = easyocr.Reader(
                self.easyocr_languages,
                gpu=self.easyocr_gpu,
            )

    def _run_easyocr(
        self,
        image: Image.Image,
        *,
        source: str,
        page_number: Optional[int] = None,
    ) -> Document:
        self._initialize_easyocr()
        results = self.easy_reader.readtext(
            np.asarray(image.convert("RGB")),
            detail=1,
            paragraph=False,
        )

        text_parts, detections = [], []
        for bbox, text, confidence in results:
            text = str(text).strip()
            if not text:
                continue
            text_parts.append(text)
            detections.append({
                "text": text,
                "confidence": float(confidence),
                "bbox": [[float(x), float(y)] for x, y in bbox],
            })

        return self._make_document(
            "\n".join(text_parts),
            source=source,
            engine="easyocr",
            page_number=page_number,
            detections=detections,
            extra_metadata={
                "language": self.easyocr_languages,
                "detection_count": len(detections),
            },
        )

    def easyocr_image(self, image_path: str | Path) -> Document:
        """OCR one image and return one LangChain Document."""
        path = self._validate_file(image_path)
        return self._run_easyocr(self._open_image(path), source=str(path))

    def easyocr_pdf_page(
        self, pdf_path: str | Path, page_number: int, dpi: Optional[int] = None
    ) -> Document:
        """OCR only one PDF page (1-indexed)."""
        path = self._validate_file(pdf_path)
        with self._open_pdf(path) as pdf:
            self._validate_page_number(pdf, page_number)
            image = self._render_page(pdf[page_number - 1], dpi or self.default_dpi)
        return self._run_easyocr(
            image, source=str(path), page_number=page_number
        )

    def easyocr_pdf(
        self, pdf_path: str | Path, dpi: Optional[int] = None
    ) -> list[Document]:
        """OCR every page of a PDF independently."""
        path = self._validate_file(pdf_path)
        documents = []
        with self._open_pdf(path) as pdf:
            for index in range(len(pdf)):
                page_number = index + 1
                image = self._render_page(pdf[index], dpi or self.default_dpi)
                documents.append(self._run_easyocr(
                    image, source=str(path), page_number=page_number
                ))
        return documents

    # ---------------------------- Tesseract ----------------------------

    def _run_tesseract(
        self,
        image: Image.Image,
        *,
        source: str,
        page_number: Optional[int] = None,
        language: str = "eng",
        config: str = "--psm 3",
    ) -> Document:
        data = pytesseract.image_to_data(
            image,
            lang=language,
            config=config,
            output_type=Output.DICT,
        )

        text_parts, detections = [], []
        for i, raw_text in enumerate(data["text"]):
            text = str(raw_text).strip()
            try:
                confidence = float(data["conf"][i])
            except (TypeError, ValueError):
                confidence = -1.0
            if not text or confidence < 0:
                continue

            x, y = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            text_parts.append(text)
            detections.append({
                "text": text,
                "confidence": confidence / 100.0,
                "bbox": [x, y, x + w, y + h],
                "block_num": int(data["block_num"][i]),
                "par_num": int(data["par_num"][i]),
                "line_num": int(data["line_num"][i]),
                "word_num": int(data["word_num"][i]),
            })

        return self._make_document(
            " ".join(text_parts),
            source=source,
            engine="tesseract",
            page_number=page_number,
            detections=detections,
            extra_metadata={
                "language": language,
                "config": config,
                "detection_count": len(detections),
            },
        )

    def tesseract_image(
        self,
        image_path: str | Path,
        language: str = "eng",
        config: str = "--psm 3",
    ) -> Document:
        """OCR one image and return one LangChain Document."""
        path = self._validate_file(image_path)
        return self._run_tesseract(
            self._open_image(path),
            source=str(path),
            language=language,
            config=config,
        )

    def tesseract_pdf_page(
        self,
        pdf_path: str | Path,
        page_number: int,
        dpi: Optional[int] = None,
        language: str = "eng",
        config: str = "--psm 3",
    ) -> Document:
        """OCR only one PDF page (1-indexed)."""
        path = self._validate_file(pdf_path)
        with self._open_pdf(path) as pdf:
            self._validate_page_number(pdf, page_number)
            image = self._render_page(pdf[page_number - 1], dpi or self.default_dpi)
        return self._run_tesseract(
            image,
            source=str(path),
            page_number=page_number,
            language=language,
            config=config,
        )

    def tesseract_pdf(
        self,
        pdf_path: str | Path,
        dpi: Optional[int] = None,
        language: str = "eng",
        config: str = "--psm 3",
    ) -> list[Document]:
        """OCR every page of a PDF independently."""
        path = self._validate_file(pdf_path)
        documents = []
        with self._open_pdf(path) as pdf:
            for index in range(len(pdf)):
                page_number = index + 1
                image = self._render_page(pdf[index], dpi or self.default_dpi)
                documents.append(self._run_tesseract(
                    image,
                    source=str(path),
                    page_number=page_number,
                    language=language,
                    config=config,
                ))
        return documents

    # ------------------------------ FastOCR ----------------------------

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

        loader = FastOCRLoader(
            file_path=str(file_path),
            api_key=self.fastocr_api_key,
        )
        loaded_docs = loader.load()

        documents = []
        for index, loaded_doc in enumerate(loaded_docs):
            metadata = dict(loaded_doc.metadata or {})
            metadata.update({
                "source": str(file_path),
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

    def fastocr_pdf(
        self, pdf_path: str | Path, languages: str = "en"
    ) -> list[Document]:
        """Pass the entire PDF to FastOCRLoader."""
        path = self._validate_file(pdf_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file: {path}")
        return self._run_fastocr(path, languages=languages)

    def fastocr_pdf_page(
        self,
        pdf_path: str | Path,
        page_number: int,
        dpi: Optional[int] = None,
        languages: str = "en",
    ) -> list[Document]:
        """
        Render only the requested PDF page and pass the temporary PNG
        to FastOCRLoader. This assumes FastOCRLoader accepts image paths.
        Verify that behavior with your installed langchain-fastocr version.
        """
        path = self._validate_file(pdf_path)
        with self._open_pdf(path) as pdf:
            self._validate_page_number(pdf, page_number)
            image = self._render_page(pdf[page_number - 1], dpi or self.default_dpi)

        with tempfile.TemporaryDirectory(prefix="fastocr_page_") as temp_dir:
            image_path = Path(temp_dir) / f"page_{page_number}.png"
            image.save(image_path, format="PNG")
            return self._run_fastocr(
                image_path,
                page_number=page_number,
            )

    def fastocr_image(
        self, image_path: str | Path, languages: str = "en"
    ) -> list[Document]:
        """Pass one image to FastOCRLoader (requires image-path support)."""
        path = self._validate_file(image_path)
        if path.suffix.lower() not in self.SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image format: {path.suffix}")
        return self._run_fastocr(path, languages=languages)



ocr_client = OCRClient()
if __name__ == "__main__":
    pdf_path= r"C:\Users\miyas\Downloads\Merging pdfs\cr7_merged.pdf"
    image_path= r"C:\Users\miyas\Downloads\TEmpo\bannar.png"
    # Entire PDF
    docs = ocr_client.easyocr_pdf(pdf_path)
    print("=====[Entire Documents]=====")
    print(docs)
    print("=====[End of Entire Documents]=====")
    # Specific PDF page (1-indexed)
    doc = ocr_client.easyocr_pdf_page(pdf_path, page_number=1)
    print("=====[Single Page Document]=====")
    print(doc)
    print("=====[End of Single Page Document]=====")
    
    # Image
    doc = ocr_client.easyocr_image(image_path)
    print("=====[Image Document]=====")
    print(doc)
    print("=====[End of Image Document]=====")
    # 
    # Same operations for other engines
    docs = ocr_client.tesseract_pdf(pdf_path)
    print("=====[Tesseract Entire Documents]=====")
    print(docs)
    print("=====[End of Tesseract Entire Documents]=====")
    
    doc = ocr_client.fastocr_pdf_page(pdf_path, page_number=1)
    print("=====[FastOCR Single Page Document]=====")
    print(doc)
    print("=====[End of FastOCR Single Page Document]=====")