# 22. Local Setup Guide

## Prerequisites

- Python 3.11 or newer.
- uv (recommended because the repository includes `uv.lock`), or another compatible Python environment manager.
- Access to configured PostgreSQL, Redis-compatible, Qdrant and Backblaze B2 services for the workflows that use them.
- An LLM API endpoint/key/model.
- OCR system dependencies and language data for the selected OCR engine.

## Create environment

```bash
uv sync
```

Alternatively, create and activate a virtual environment and install the project dependencies from `pyproject.toml` using your package manager.

## Configure environment

Create a local `.env` file using the template in [Configuration](05-configuration.md). Populate credentials locally; do not commit the file. Database access is required when importing/using the database module. Redis is required when its accessor is called. Qdrant/B2/model settings are required for their corresponding workflows.

## Initialize relational tables

Review `scripts/create_tables.py` and `app/core/database.py` before running. The helper uses SQLAlchemy `create_all`, which creates missing tables but does not migrate existing schemas.

## Verify setup

1. Confirm Python and package installation.
2. Confirm the configured database URI points to the intended environment.
3. Run the relevant database initialization script if appropriate.
4. Check Redis connectivity with the project helper.
5. Confirm Qdrant collection configuration and credentials.
6. Confirm B2 bucket permissions.
7. Run focused tests with external-service tests excluded where appropriate.

## Limitations

The repository currently has no complete application server entry point or API route layer. Installing dependencies and configuring services does not by itself start a usable web application.
