"""Process-wide resource limits for document batch ingestion.

Conservative defaults are configurable through environment variables.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore


def _positive_int(name: str, default: int, *, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


MAX_DOCUMENT_WORKERS = _positive_int("INGESTION_MAX_DOCUMENT_WORKERS", 5, maximum=20)
MAX_QUEUED_DOCUMENTS = _positive_int("INGESTION_MAX_QUEUED_DOCUMENTS", 50, maximum=200)
MAX_PDF_EXTRACTION_WORKERS = _positive_int("INGESTION_MAX_PDF_EXTRACTION_WORKERS", 3, maximum=10)
MAX_OCR_WORKERS = _positive_int("INGESTION_MAX_OCR_WORKERS", 2, maximum=10)
MAX_LLM_WORKERS = _positive_int("INGESTION_MAX_LLM_WORKERS", 2, maximum=10)
MAX_INDEXING_WORKERS = _positive_int("INGESTION_MAX_INDEXING_WORKERS", 2, maximum=10)
MAX_BATCH_UPLOAD_BYTES = _positive_int("INGESTION_MAX_BATCH_UPLOAD_MB", 250, maximum=2048) * 1024 * 1024

# Concurrent batches share these process-wide limits.
DOCUMENT_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_DOCUMENT_WORKERS, thread_name_prefix="savira-ingest")
QUEUE_SLOTS = BoundedSemaphore(MAX_QUEUED_DOCUMENTS + MAX_DOCUMENT_WORKERS)
PDF_EXTRACTION_SLOTS = BoundedSemaphore(MAX_PDF_EXTRACTION_WORKERS)
OCR_SLOTS = BoundedSemaphore(MAX_OCR_WORKERS)
LLM_SLOTS = BoundedSemaphore(MAX_LLM_WORKERS)
INDEXING_SLOTS = BoundedSemaphore(MAX_INDEXING_WORKERS)
