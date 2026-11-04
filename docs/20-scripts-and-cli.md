# 20. Scripts and Operational Commands

Scripts under `scripts/` are direct Python entry points rather than a unified command-line application.

| Script | Apparent responsibility |
|---|---|
| `create_tables.py` | Initialize SQLAlchemy tables |
| `database.py` | Database-related utility operations |
| `ingestion.py` | Exercise/run document ingestion |
| `qdrant.py` | Qdrant collection utility |
| `qdrant_bm25.py` | BM25-related Qdrant utility |
| `qdrant_summary_store.py` | Summary collection utility |
| `candidate_documents.py` | Candidate-document inspection |
| `reconcile_indexes.py` | Reconcile indexing/lifecycle state |

Read each script's current argument parsing and side effects before running it. The table describes the file's apparent role and is not a guarantee of safe defaults.

## General execution

Run from the repository root with the project environment activated. Use `python -m scripts.<module>` where the script supports module execution, or run its file directly if its imports require that. Supply environment configuration first.

## Safety

- Confirm target database and Qdrant environment before executing scripts.
- Treat reset/delete/recreate options as destructive.
- Back up relevant stores before bulk reconciliation or index recreation.
- Never run operational scripts against production without an approved change window.
