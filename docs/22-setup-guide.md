# 22. Local Setup Guide

## Prerequisites

- Python 3.11 or newer.
- uv (recommended because the repository includes `uv.lock`), or another compatible Python environment manager.
- Access to configured PostgreSQL, Redis-compatible, Qdrant and Backblaze B2 services for workflows that use them.
- An LLM API endpoint/key/model.
- OCR system dependencies and language data for the selected OCR engine.

## Create environment

```powershell
uv sync
```

Alternatively, create and activate a virtual environment and install the project dependencies from `pyproject.toml` using your package manager.

## Configure environment

Create a local `.env` file using the template in [Configuration](05-configuration.md). Populate credentials locally; do not commit the file. Database access is required when importing/using the database module. Redis is required when `get_redis()` is called. Qdrant/B2/model settings are required for their corresponding workflows.

## Database schema warning

The repository has no checked-in migration history. Do **not** assume `scripts/create_tables.py` is a safe create-only command: it calls `scripts/database.py`, which drops and recreates all SQLAlchemy-managed tables after interactive confirmation, deleting their data. Review the script and target database carefully; use only against a disposable/empty development database when a reset is intended. `Base.metadata.create_all()` in the database helper only creates missing registered tables and does not migrate existing schemas.

## Verify setup

1. Confirm Python and package installation.
2. Confirm the configured database URI points to the intended environment.
3. Initialize/reset a disposable development schema only when explicitly intended.
4. Check Redis connectivity with the project helper if using the cache service.
5. Confirm Qdrant collection configuration and credentials.
6. Confirm B2 bucket permissions.
7. Confirm the selected OCR engine and language packs are installed.
8. Run focused tests with external-service tests excluded where appropriate.

## Limitations

The repository currently has no complete application server entry point or API route layer. Installing dependencies and configuring services does not by itself start a usable web application.
