# 24. Error Handling and Recovery

## Error categories

- Configuration errors: missing database/Redis credentials or invalid environment values.
- PDF errors: invalid/corrupt file, unreadable pages, no usable text, page-count mismatch.
- LLM errors: provider/network failures, invalid structured output or unavailable model.
- Matching errors: inconsistent or failed duplicate lookup.
- Storage errors: B2 upload/download/delete failure.
- Database errors: connection, constraint, transaction or repository failure.
- Vector-store errors: Qdrant connection, collection, payload or upsert failure.
- Authorization/cache errors: unresolved identity/scope, cache connectivity or stale entries.

## Transaction and cleanup behavior

The database session context rolls back when an exception escapes and always closes the session; it does not commit automatically. Ingestion attempts to clean up an uploaded object when subsequent registration fails. Indexing must coordinate relational lifecycle changes with Qdrant operations and may require reconciliation after partial failure.

## Recovery principles

1. Preserve the original exception and its context.
2. Determine which stores were modified before failure.
3. Check the relational document/version state.
4. Check the B2 object exists and corresponds to the expected storage key/hash.
5. Check chunk and summary collections for the affected document/version.
6. Use the reconciler only for states it explicitly supports.
7. Re-run idempotent operations only after confirming duplicate/partial-write behavior.

## Logging

Log operation IDs, document/version identifiers and stage outcomes where permitted. Do not log API keys, database connection strings, raw document contents or unnecessary personal data. Keep external provider error messages sanitized.

## Escalation

If state differs between PostgreSQL, B2 and Qdrant and the reconciler cannot safely repair it, stop automated retries and perform a controlled recovery with backups and a documented audit trail.
