# 8. PDF Processing

## Components

- `app/rag/pdf_reader/validator.py`: validates file existence/type, size, PDF signature, password protection, page count and page accessibility.
- `native.py`: native page text extraction.
- `ocr.py`: EasyOCR, Tesseract and FastOCR adapters.
- `loader.py`: native-first extraction and page-level OCR policy.
- `app/rag/ingestion/text_normalizer.py`: normalizes extracted page text.
- `pdf_sampler.py`: selects representative pages for summarization.
- `hash_service.py`: computes file and normalized-content SHA-256 hashes.

## Validation limits

The default `PDFValidator` limits are 100 MiB and 2,000 pages. It checks the extension, file size, PDF signature in the first 1,024 bytes, structural readability, password protection and page accessibility. Filename-based MIME detection produces a warning rather than being treated as definitive validation. These limits can be changed by constructing the validator with other values.

## Extraction and OCR policy

The loader extracts native text first. It attempts OCR for a page when `OCR_ALL_PAGES` is true or the count of non-whitespace native characters is below `MIN_NATIVE_CHARS`. The loader supports `easyocr`, `tesseract`, and `fastocr`; the default engine is EasyOCR and the default language is English.

OCR output is not automatically trusted. When native text exists, OCR is considered usable only if it is non-empty and its mean confidence is either unavailable or at least 0.5. OCR replaces native text only when it is longer and usable. When `OCR_MERGE_WITH_NATIVE` is enabled, usable OCR can be merged under the loader's additional quality checks; otherwise native text is retained unless OCR is better. Metadata records page number, native/OCR lengths, whether OCR was attempted/used, confidence when available, and extraction method.

## Processing sequence

1. Validate the PDF.
2. Extract native text page by page.
3. Evaluate the per-page OCR policy and run the configured OCR adapter when required.
4. Normalize page text while retaining page metadata.
5. Reject ingestion if extracted page count differs from validator page count or all normalized page text is empty.
6. Calculate file and normalized-content hashes.
7. Select up to five evenly distributed pages by default for summarization. All extracted pages—not only sampled pages—are later used for indexing.

Tests demonstrate 1-based `page` metadata and an `ocr_used` flag.

## Configuration

See [Configuration](05-configuration.md): `OCR_ENGINE`, `OCR_LANGS`, `RENDER_DPI`, `MIN_NATIVE_CHARS`, `OCR_ALL_PAGES`, `OCR_MERGE_WITH_NATIVE`, and `FASTOCR_API_KEY`. Install the selected OCR engine's runtime dependencies and language data on the host.

## Operational notes

Test text-native and scanned PDFs separately. Verify OCR language packs and system executables. Choose DPI based on accuracy/resource tradeoffs and keep page numbering stable for provenance. Files in `data/` are development fixtures, not production inputs.
