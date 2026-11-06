# SaviraCortex Backend

FastAPI backend and document-intelligence/RAG services for SaviraCortex.

## Run locally

Activate the backend virtual environment, then from this directory:

```powershell
uvicorn app.main:app --reload
```

API documentation:
- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc

## Run tests

```powershell
python -m pytest
```

Latest focused auth/department schema checkpoint (5 November 2026):

```powershell
python -m pytest tests/test_v1_department_schemas.py tests/test_v1_auth_schemas.py tests/services/test_auth_services.py -v
```

Reported result: 20 passed in 2.33 seconds. This is not a full-suite result.

## Configuration

Configure backend environment variables in a local `.env` file. Firebase Admin uses the backend-only service-account JSON configured by `FIREBASE_SERVICE_ACCOUNT_PATH` (default: `app/secrets/firebase-service-account.json`). Never commit that credential file.

## Technical documentation

The numbered engineering documentation is in [docs/](docs/README.md). Start with [the current application checkpoint](docs/30-current-application-checkpoint.md) for the latest implementation status, test evidence and next steps.
