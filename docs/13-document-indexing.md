# 13. Document Indexing

## Components

- `indexing_service.py`: performs per-version indexing operations.
- `indexing_orchestrator.py`: coordinates the end-to-end indexing and activation sequence.
- `lifecycle_reconciler.py`: repairs selected mismatches between relational and vector-store lifecycle state.
- RAG adapters: PDF loader, recursive splitter, embedding adapter and Qdrant stores.

## Logical sequence

1. Load the pending version and its stored PDF.
2. Verify/read the source document and extract page content.
3. Split page documents into chunks while retaining metadata.
4. Generate embeddings for chunk content.
5. Write chunk vectors and payload metadata to the configured Qdrant collection.
6. Generate/store document-level summary representation in the summary collection.
7. Update relational version lifecycle state and commit.
8. Synchronize vector-store lifecycle state for active/superseded versions.
9. Reconcile incomplete cross-store operations where supported.

Exact ordering and compensation behavior are defined in `indexing_orchestrator.py`; consult it before operating on partially indexed versions.

## Chunk metadata

Retrieval and lifecycle filters depend on payload attributes. Preserve document identity, version identity, organization scope, page provenance and status fields when changing chunk construction or Qdrant payload schema.

## Concurrency and consistency

Integration tests cover indexing concurrency and lifecycle behavior. The database and Qdrant do not participate in a shared transaction, so a partial failure may leave stale vector payloads or an incomplete summary record. The reconciler exists to bring supported states back into alignment.

## Tests

See `tests/services/test_document_indexing.py`, `test_document_indexing_orchestrator.py`, `test_document_indexing_integration.py`, `test_lifecycle_reconciler.py`, and `tests/integration/test_document_indexing_concurrency.py`.
