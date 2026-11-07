# 21. Testing

## Framework and configuration

pytest is used for backend tests. The backend test tree includes agent, evaluation, integration, RAG, service, storage and workflow coverage. Frontend scripts are defined in `frontend/package.json` (`npm run lint`, `npm run build`).

## Test organization

- `tests/agent/`: agent behavior and structured-output tests.
- `tests/workflows/`: LangGraph node adapters, routing and graph tests.
- `tests/integration/`: indexing, summary-store and retrieval integration.
- `tests/rag/`: retrieval algorithms, fusion, reranking, adaptive-K and vector-store tests.
- `tests/services/`: ingestion, registration, indexing, lifecycle, retrieval, auth and document deletion services.
- `tests/storage/`: object-storage behavior.
- Root-level tests: authorization, repositories, PDF handling, hashing, normalization, storage and API contracts/endpoints.

## Running tests

From `E:\SaviraCortex\backend`:

```powershell
uv run pytest
```

Focused document-management tests:

```powershell
uv run pytest tests/test_v1_documents_endpoints.py tests/services/test_document_deletion.py -v
```

Focused ingestion tests:

```powershell
uv run pytest tests/test_v1_document_ingestion_endpoints.py tests/services/test_document_ingestion_workflow.py -v
```

Workflow tests:

```powershell
uv run pytest tests/workflows -v
```

Frontend checks from `frontend/`:

```powershell
npm run lint
npm run build
```

## Historical verification checkpoints

### RAG workflow checkpoint — 5 November 2026

Previously reported by the user:
- `uv run pytest tests/workflows -v`: 45 passed in 29.84 seconds.
- `pytest -v`: 393 passed, 2 warnings in 163.43 seconds.
- Retrieval-exclusion focused suite: 49 passed in 92.79 seconds.

These are historical results and do not establish that the current working tree passes.

### Authentication/department schema checkpoint — 5 November 2026

Previously reported:
```powershell
python -m pytest tests/test_v1_department_schemas.py tests/test_v1_auth_schemas.py tests/services/test_auth_services.py -v
```
Result: 20 passed in 2.33 seconds.

This selection did not cover all current organization, invitation, ingestion, document-library or generation endpoint behavior.

## Current documentation checkpoint — 7 November 2026

No tests were run as part of this documentation refresh. The current workspace contains uncommitted backend and frontend implementation changes, including document-management and ingestion work. Do not report the historical results as verification of those changes.

Before committing a feature, run the smallest relevant focused test selection, inspect `git diff --check`, and record the exact command and result. Run broader suites when requested or when the change scope warrants them.

## External dependencies and safety

Some tests require PostgreSQL, Redis/Valkey, Qdrant, model credentials or OCR dependencies. Use isolated test services and test credentials. Do not run integration tests against production data. Verify organization/user identity and test data before running live E2E scripts.
