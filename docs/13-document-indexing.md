# 13. Document Indexing

## Components

- `indexing_service.py`: splits extracted pages into chunks, attaches metadata, creates deterministic Qdrant point IDs and inserts chunk vectors.
- `indexing_orchestrator.py`: validates/downloads a pending version, verifies the stored PDF, writes chunk and summary records, activates the version in PostgreSQL, then synchronizes Qdrant lifecycle metadata.
- `lifecycle_reconciler.py`: replays authoritative PostgreSQL lifecycle state to existing Qdrant chunk and summary records.
- RAG adapters: PDF loader, recursive splitter, embedding adapter and Qdrant stores.

## Actual orchestration sequence

1. Load and lock the target version and parent document in PostgreSQL. Only a non-archived document's `pending` version is accepted.
2. Validate required metadata, including storage key, SHA-256 file hash, summary and document title.
3. Download the original PDF from B2 into a temporary directory.
4. Recalculate SHA-256 and reject the download if it does not match the registered file hash.
5. Extract all pages and index all non-empty chunks in the Qdrant chunk collection. The summarizer's sampled pages are not used as the chunk source.
6. Upsert the document-version summary into the summary collection with `pending` status.
7. Update the actual extracted page count and activate the version in PostgreSQL. The repository marks the previously active version `superseded` as part of the lifecycle transaction.
8. After the PostgreSQL commit, update the new version's chunk status to `active`, the previous version's chunk status to `superseded`, and upsert the summary point with `active` status.
9. Return an `IndexingOrchestrationResult` containing page/OCR/chunk counts, Qdrant point IDs, summary point ID, status and any pending synchronization/errors.

## Chunk metadata and identity

Each chunk receives organization ID, logical document ID, version ID, version number, source filename, zero-based chunk index and initial `pending` status. Point IDs are deterministic UUID5 values derived from the version ID and chunk index. Page provenance from the PDF loader is retained in chunk metadata.

Retrieval filters depend on organization, document/version and lifecycle metadata. Preserve these fields when changing chunk construction or Qdrant payload schema.

## Failure and consistency behavior

PostgreSQL is authoritative for lifecycle state; it does not share a transaction with Qdrant. Before a confirmed database commit, failures trigger compensating deletion of inserted chunk points and the attempted summary point, followed by database rollback. The original B2 PDF is deliberately not deleted by indexing cleanup.

If the PostgreSQL commit was attempted but its outcome is uncertain, the orchestrator preserves external index data rather than risk deleting records for a possibly committed version. After a successful commit, Qdrant chunk-status and summary-status synchronization failures are reported as pending synchronization; they do not roll back the committed PostgreSQL activation.

The reconciler repairs lifecycle projections and re-upserts summary points for versions currently marked `active` or `superseded` in PostgreSQL. It does not recreate missing chunk vectors or rerun PDF extraction.

## Tests

See `tests/services/test_document_indexing.py`, `test_document_indexing_orchestrator.py`, `test_document_indexing_integration.py`, `test_lifecycle_reconciler.py`, and `tests/integration/test_document_indexing_concurrency.py`.
