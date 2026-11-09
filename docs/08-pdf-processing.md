# 8. PDF Processing

## Components

- `app/rag/pdf_reader/validator.py`: validates file existence/type, size, PDF signature, password protection, page count and page accessibility.
- `native.py`: native page text extraction.
- `ocr.py`: FastOCR SDK adapter routed through the local API gateway; no local OCR model is loaded.
- `loader.py`: native-first extraction and selected-page batch OCR policy.
- `app/rag/ingestion/text_normalizer.py`: normalizes extracted page text.
- `pdf_sampler.py`: selects representative pages for summarization.
- `hash_service.py`: computes file and normalized-content SHA-256 hashes.

## Validation limits

The default `PDFValidator` limits are 100 MiB and 2,000 pages. It checks the extension, file size, PDF signature in the first 1,024 bytes, structural readability, password protection and page accessibility. Filename-based MIME detection produces a warning rather than being treated as definitive validation. These limits can be changed by constructing the validator with other values.

## Extraction and OCR policy

The loader extracts native text first. When `OCR_ALL_PAGES` is true or a page has fewer than `MIN_NATIVE_CHARS` non-whitespace characters, that page is selected for OCR. All selected pages from one source PDF are copied into one temporary PDF and submitted as a single FastOCR document job; unselected pages are never sent to the OCR provider. The returned searchable PDF is read locally with PyMuPDF and its page text is mapped back to the original 1-based page numbers. If FastOCR rejects a start with `concurrency_limit`, the backend resubmits the original selected-pages PDF as a new job, allowing the gateway to assign another eligible account; this is bounded by `FASTOCR_MAX_ACCOUNT_FALLBACKS`. The backend does not re-submit `buy_pages` monthly page-quota failures. The FastOCR SDK's authenticated document API calls go through the local API gateway; its presigned upload and output transfers go directly to FastOCR storage. Provider keys live only in `api-gateway/.env`; the backend authenticates using `FASTOCR_GATEWAY_API_KEY`, which falls back to `JINA_API_KEY`. No EasyOCR or Tesseract model/runtime is used.

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

See [Configuration](05-configuration.md): `MIN_NATIVE_CHARS`, `OCR_ALL_PAGES`, `OCR_MERGE_WITH_NATIVE`, `FASTOCR_GATEWAY_BASE_URL`, and `FASTOCR_PROCESS_TIMEOUT_SECONDS`. Configure the provider key pool in `api-gateway/.env`; no local OCR model or system OCR executable needs to be installed.

## Operational notes

Test text-native and scanned PDFs separately. The selected-page batch preserves source page numbering while reducing API document jobs and avoids sending text-native pages unnecessarily. FastOCR account page allowance still applies to each submitted page. Files in `data/` are development fixtures, not production inputs.
