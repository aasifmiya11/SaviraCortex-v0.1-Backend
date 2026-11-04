# 25. Operational Runbook

This runbook is an operational checklist derived from implemented components. It does not assert that monitoring, alerting or deployment automation is already configured.

## Before processing documents

- Verify database, Redis (only if using the cache helper), Qdrant, B2 and LLM service health.
- Confirm environment variables target the intended environment.
- Confirm the B2 bucket and both Qdrant collection names.
- Confirm OCR binaries/language packs are available for the selected engine.
- Confirm sufficient storage and service quotas.
- Verify the caller's organization/user identity and access scope.

## Ingestion issue

1. Capture the ingestion outcome and failing stage.
2. Validate the source PDF and page count (default validator limits: 100 MiB and 2,000 pages).
3. Check native extraction/OCR policy and usable text.
4. Compare file/content hashes for exact duplicates.
5. If upload succeeded but registration failed, verify object cleanup or remove an orphan through an approved procedure.
6. Do not auto-accept a potential summary match without review.

## Indexing issue

1. Identify the logical document and version.
2. Check version status in PostgreSQL; only pending versions can be indexed.
3. Check whether the original object exists in B2 and whether its SHA-256 matches the registered file hash.
4. Check chunk and summary records in Qdrant.
5. Inspect `summary_sync_pending`, `lifecycle_sync_pending` and `sync_errors` in the indexing result.
6. Run `scripts/reconcile_indexes.py` first in dry-run mode; use `--apply` only after reviewing the planned changes.
7. Remember that reconciliation repairs lifecycle metadata and summary points; it does not recreate missing chunk vectors.

## Retrieval issue

1. Confirm user membership and organization scope.
2. Confirm expected document versions appear in the PostgreSQL-derived authorized catalogue.
3. Check active/superseded/archive status.
4. Verify summary candidate generation, its similarity threshold and any per-query retrieval errors.
5. Compare dense and lexical retrieval results using the requested retrieval mode.
6. Inspect global fusion provenance, reranker scores and adaptive expansion stop reason.
7. Remember that the current retrieval orchestrator calls `AuthorizationService` directly; Redis authorization caching is not wired into that path.

## Backups and restore

A production backup plan should cover PostgreSQL, B2 originals, Qdrant chunk collection and Qdrant summary collection. Redis authorization caches are intended to be rebuildable from authoritative records when the cache wrapper is used, but verify actual application dependencies before discarding them. Test restoration and cross-store reconciliation regularly.

## Known gaps at review time

- No implemented API route layer or complete server startup path was found.
- No populated migration directory was found.
- The DepartmentAccessPolicy model module is not imported by `app.models`' package initializer, so it is not registered by the current package import alone.
- Dedicated observability and task/worker packages were empty.
- No deployment manifests or production runbook were found in the reviewed root tree.
- The full test suite and production-like recovery were not executed during this documentation audit.
