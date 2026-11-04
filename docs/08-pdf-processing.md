# 8. PDF Processing

## Components

- `app/rag/pdf_reader/validator.py`: validates PDF inputs and reports page count/errors/warnings.
- `native.py`: native page text extraction.
- `ocr.py`: page rendering and OCR engine adapters.
- `loader.py`: orchestrates extraction and OCR policy.
- `app/rag/ingestion/text_normalizer.py`: normalizes extracted page text.
- `pdf_sampler.py`: selects representative pages for summarization.
- `hash_service.py`: computes file/content hashes.

## Processing sequence

1. Validate the PDF.
2. Determine page count and reject invalid/unusable files.
3. Extract native text page by page.
4. Evaluate OCR policy using configured threshold and flags.
5. Render pages at configured DPI and invoke selected OCR backend when required.
6. Apply OCR/native merge policy.
7. Return page-level LangChain Document objects with metadata.
8. Normalize text while retaining page metadata.

Tests demonstrate metadata including a 1-based `page` number and `ocr_used` flag. The ingestion service stops before matching/upload/registration if validation fails, extracted page count differs from validator count, or usable text is absent.

## Configuration

See [Configuration](05-configuration.md): `OCR_ENGINE`, `OCR_LANGS`, `RENDER_DPI`, `MIN_NATIVE_CHARS`, `OCR_ALL_PAGES`, `OCR_MERGE_WITH_NATIVE`, and `FASTOCR_API_KEY`. Supported engine names and fallback behavior are defined in `ocr.py` and `loader.py`; install the relevant native/runtime dependencies on the host.

## Operational notes

Test text-native and scanned PDFs separately. Verify OCR language packs and system executables. Choose DPI based on accuracy/resource tradeoffs and keep page numbering stable for provenance. Files in `data/` are development fixtures, not production inputs.
