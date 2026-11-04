# 20. Scripts and Command-Line Utilities

The repository has several independent Python scripts and no unified CLI application. Run commands from the repository root after configuring the environment. Inspect arguments and side effects before use.

## Scripts under `scripts/`

| Script | Actual behavior |
|---|---|
| `database.py` | Destructively drops and recreates all SQLAlchemy-managed tables after exact interactive confirmation |
| `create_tables.py` | Compatibility entry point that calls the same destructive `reset_database()`; despite its name, it is not a non-destructive create-only command |
| `ingestion.py` | Creates a fresh demo organization, user and owner membership; ingests a PDF; associates the uploader; optionally indexes the pending version |
| `qdrant.py` | Lists/counts/shows chunk points; deletes by document ID or source; can wipe and recreate the chunk collection with `wipe --confirm` |
| `qdrant_bm25.py` | Runs a Qdrant BM25 query scoped by required organization ID, with optional document/user/status filters |
| `qdrant_summary_store.py` | Counts/lists/shows document-version summary points with optional payload filters |
| `candidate_documents.py` | Generates and prints candidate document versions from an authorized PostgreSQL catalogue and Qdrant summary similarity |
| `reconcile_indexes.py` | Dry-runs by default; with `--apply`, synchronizes Qdrant chunk lifecycle payloads and re-upserts summary points from PostgreSQL |

## Common invocations

```powershell
# Ingest and index a PDF using a newly created demo tenant
uv run python scripts/ingestion.py "C:\path\to\document.pdf"

# Stop after pending registration
uv run python scripts/ingestion.py "C:\path\to\document.pdf" --skip-index

# Preview lifecycle reconciliation (default; no Qdrant writes)
uv run python scripts/reconcile_indexes.py

# Apply lifecycle metadata/summary synchronization
uv run python scripts/reconcile_indexes.py --apply

# Search Qdrant BM25
uv run python scripts/qdrant_bm25.py "leave policy" --organization-id <ORG_UUID>
```

The ingestion demo creates a new tenant/user each run; it is not a production upload command. The reconciliation script does not rebuild missing chunk vectors or rerun PDF extraction.

## Separate root-level utility

`storage.py` is a standalone B2 command-line tool with `test`, `upload`, `list`, `download`, `read`, and `delete` subcommands. It is separate from `app/storage/file_storage.py`.

## Operational safety

- **Database reset:** `scripts/database.py` and `scripts/create_tables.py` delete data in all registered SQLAlchemy-managed tables after confirmation. Never use them against a database containing data you need.
- **Qdrant wipe/delete:** `scripts/qdrant.py wipe --confirm` deletes and recreates the entire chunk collection; delete subcommands permanently remove matching points.
- **Storage delete:** `storage.py delete` asks for an interactive confirmation.
- Confirm target database, bucket and Qdrant collection before running any mutating command. Back up relevant stores and use an approved change window for production operations.
