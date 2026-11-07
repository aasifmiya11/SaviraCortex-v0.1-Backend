# SaviraCortex Backend

FastAPI backend and document-intelligence/RAG services for SaviraCortex.

## Run locally

From this directory:

```powershell
uv sync
uv run uvicorn app.main:app --reload
```

API documentation:
- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc

## Run tests

```powershell
uv run pytest
```

Use focused tests while developing and record the exact command and result. See [Testing](docs/21-testing.md).

## Configuration

Configure backend environment variables in a local `.env` file. Firebase Admin uses the backend-only service-account JSON configured by `FIREBASE_SERVICE_ACCOUNT_PATH` (default: `app/secrets/firebase-service-account.json`). Never commit that credential file.

## Technical documentation

- [Documentation index](docs/README.md)
- [Project overview](docs/01-project-overview.md)
- [System architecture](docs/02-system-architecture.md)
- [Configuration](docs/05-configuration.md)
- [Database design](docs/06-database-design.md)
- [Authorization](docs/07-authorization.md)
- [Document ingestion](docs/09-document-ingestion.md)
- [Retrieval architecture](docs/15-retrieval-architecture.md)
- [Generation pipeline](docs/26-generation-pipeline.md)
- [Project-wide current state](docs/31-project-wide-current-state.md)

The companion frontend is maintained in the [SaviraCortex Frontend repository](https://github.com/miyasajid19/SaviraCortex-Frontend).
