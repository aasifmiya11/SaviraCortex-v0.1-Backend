# 24. Error Handling and Recovery

## Error categories

- Configuration errors: missing database/Redis/B2 credentials or invalid environment values.
- PDF errors: invalid/corrupt/password-protected file, unreadable pages, no usable text, page-count mismatch.
- LLM errors: provider/network failures, refusal, invalid structured output or unavailable model.
- Matching errors: inconsistent or failed duplicate lookup.
- Storage errors: B2 upload/download/delete failure or uploaded-size mismatch.
- Database errors: connection, constraint, transaction or repository failure.
- Vector-store errors: Qdrant connection, collection, payload or upsert failure.
- Authorization/cache errors: unresolved membership/scope, cache connectivity or stale entries.

## Ingestion transaction and cleanup

The database session context rolls back when an exception escapes and always closes the session; it does not commit automatically. The ingestion service holds organization-scoped hash locks while matching and registering. If upload or registration fails, it rolls back and attempts to delete the uploaded B2 object. A cleanup failure is retained on `DocumentIngestionError.cleanup_error`.

## Indexing compensation and uncertain commits

Indexing verifies the downloaded B2 PDF against its registered SHA-256 before extraction. If chunk/summary writes or activation fail before commit, it attempts to delete inserted chunk points and the summary point, then rolls back PostgreSQL. The original B2 object is deliberately retained.

If the PostgreSQL commit was attempted but its outcome is uncertain, the orchestrator preserves external Qdrant data rather than risk deleting data belonging to a possibly committed version. After a successful commit, chunk and summary lifecycle updates run separately. Failures are returned as `lifecycle_sync_pending`, `summary_sync_pending`, and `sync_errors`; they do not undo the committed PostgreSQL state.

## Recovery principles

1. Preserve the original exception and its context.
2. Determine which stores were modified before failure.
3. Check the relational document/version state; PostgreSQL is authoritative for lifecycle.
4. Check the B2 object exists and corresponds to the expected storage key/hash.
5. Check chunk and summary collections for the affected document/version.
6. Use `scripts/reconcile_indexes.py` only for lifecycle projection repair. Its default mode is dry-run; `--apply` updates lifecycle payloads and re-upserts summaries for active/superseded versions.
7. Do not expect the reconciler to rebuild missing chunk vectors or rerun PDF extraction.
8. Re-run idempotent operations only after confirming duplicate/partial-write behavior.

## Logging

Log operation IDs, document/version identifiers and stage outcomes where permitted. Do not log API keys, database connection strings, raw document contents or unnecessary personal data. Keep external provider error messages sanitized.

## Escalation

If state differs between PostgreSQL, B2 and Qdrant and the reconciler cannot safely repair it, stop automated retries and perform a controlled recovery with backups and a documented audit trail.
