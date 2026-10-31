
from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

import fitz


@dataclass
class PDFValidationResult:
    is_valid: bool
    file_path: str
    file_size: int = 0
    page_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PDFValidator:
    """
    Validates uploaded PDF files before ingestion.

    This component performs file-level and structural validation.
    It does not extract PDF text or perform OCR.
    """

    PDF_SIGNATURE = b"%PDF-"

    def __init__(
        self,
        max_file_size_mb: int = 100,
        max_pages: int = 2000,
    ):
        if max_file_size_mb <= 0:
            raise ValueError("Maximum file size must be positive.")

        if max_pages <= 0:
            raise ValueError("Maximum page count must be positive.")

        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.max_pages = max_pages

    def validate(self, file_path: str | Path) -> PDFValidationResult:

        path = Path(file_path).expanduser()

        errors: list[str] = []
        warnings: list[str] = []

        file_size = 0
        page_count = 0

        # 1. Check whether the file exists.
        if not path.exists():
            errors.append("File does not exist.")
            return self._build_result(
                path, file_size, page_count, errors, warnings
            )

        if not path.is_file():
            errors.append("Provided path is not a file.")
            return self._build_result(
                path, file_size, page_count, errors, warnings
            )

        # 2. Check file extension.
        if path.suffix.lower() != ".pdf":
            errors.append("File extension must be .pdf.")

        # 3. Check file size.
        try:
            file_size = path.stat().st_size
        except OSError as exc:
            errors.append(f"Unable to access file: {exc}")
            return self._build_result(
                path, file_size, page_count, errors, warnings
            )

        if file_size == 0:
            errors.append("File is empty.")

        if file_size > self.max_file_size_bytes:
            errors.append(
                f"File exceeds the maximum allowed size of "
                f"{self.max_file_size_bytes // (1024 * 1024)} MB."
            )

        if errors:
            return self._build_result(
                path, file_size, page_count, errors, warnings
            )

        # 4. Preliminary MIME type check.
        mime_type, _ = mimetypes.guess_type(path.name)

        if mime_type != "application/pdf":
            warnings.append(
                "Filename-based MIME detection did not identify "
                "application/pdf. This is not a definitive file check."
            )

        # 5. Check PDF signature.
        try:
            with path.open("rb") as file:
                header = file.read(1024)

            if self.PDF_SIGNATURE not in header:
                errors.append(
                    "PDF signature (%PDF-) not found in the first "
                    "1024 bytes."
                )

        except OSError as exc:
            errors.append(f"Unable to read file: {exc}")

        if errors:
            return self._build_result(
                path, file_size, page_count, errors, warnings
            )

        # 6. Structural validation using PyMuPDF.
        try:
            with fitz.open(path) as pdf:

                if not pdf.is_pdf:
                    errors.append("File is not recognized as a PDF.")

                if pdf.needs_pass:
                    errors.append(
                        "PDF is password-protected. "
                        "Password authentication is not supported yet."
                    )

                else:
                    # 7. Check page count.
                    page_count = pdf.page_count

                    if page_count == 0:
                        errors.append("PDF contains no pages.")

                    if page_count > self.max_pages:
                        errors.append(
                            f"PDF exceeds the maximum allowed page count "
                            f"of {self.max_pages}."
                        )

                    # 8. Check page accessibility.
                    if not errors:
                        for page_index in range(page_count):
                            try:
                                pdf.load_page(page_index)

                            except Exception as exc:
                                errors.append(
                                    f"Unable to access page "
                                    f"{page_index + 1}: {exc}"
                                )
                                break

        except Exception as exc:
            errors.append(
                f"PDF structural validation failed: {exc}"
            )

        return self._build_result(
            path,
            file_size,
            page_count,
            errors,
            warnings,
        )

    @staticmethod
    def _build_result(
        path: Path,
        file_size: int,
        page_count: int,
        errors: list[str],
        warnings: list[str],
    ) -> PDFValidationResult:

        return PDFValidationResult(
            is_valid=len(errors) == 0,
            file_path=str(path),
            file_size=file_size,
            page_count=page_count,
            errors=errors,
            warnings=warnings,
        )
