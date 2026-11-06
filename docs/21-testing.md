# 21. Testing

## Framework and configuration

pytest is used for backend tests. The project uses asyncio-related pytest plugins and includes integration-oriented test areas. Check the current test configuration and fixtures before relying on commands in CI.

## Test organization

- `tests/agent/`: agent behavior and structured-output tests.
- `tests/workflows/`: LangGraph node adapters, routing and end-to-end graph tests.
- `tests/integration/`: indexing, summary-store and retrieval integration.
- `tests/rag/` and `tests/rag/retrieval/`: dense, BM25/hybrid retrieval, fusion, reranking, adaptive-K and candidate generation.
- `tests/services/`: ingestion, registration, indexing, lifecycle, retrieval and auth services.
- Root-level tests: authorization, repositories, PDF handling, hashing, normalization, storage and API schema validation.

## Running tests

From `E:\\SaviraCortex\\backend` with the backend virtual environment active:

```powershell
python -m pytest
```

Run the current focused authentication and department schema suite:

```powershell
python -m pytest tests/test_v1_department_schemas.py tests/test_v1_auth_schemas.py tests/services/test_auth_services.py -v
```

Run workflow tests:

```powershell
python -m pytest tests/workflows -v
```

Run a focused module:

```powershell
python -m pytest tests/workflows/test_graph.py -v
```

## Verification checkpoints

### Earlier RAG workflow checkpoint — 5 November 2026

The user reported:
- `uv run pytest tests/workflows -v`: 45 passed in 29.84 seconds.
- `pytest -v`: 393 passed, 2 warnings in 163.43 seconds.
- Retrieval-exclusion focused suite: 49 passed in 92.79 seconds.

A local workflow E2E smoke-test runner was also used with a synthetic indexed policy PDF. Evidence availability differed across test identities/scenarios, leaving tenant-scoped retrieval behavior as an open investigation. These results do not establish production readiness or prove tenant isolation.

### Authentication and department schema checkpoint — 5 November 2026

The user ran:

```powershell
python -m pytest tests/test_v1_department_schemas.py tests/test_v1_auth_schemas.py tests/services/test_auth_services.py -v
```

Reported result: **20 passed in 2.33 seconds**.

Breakdown:
- 7 department request-schema cases (trimming, blank description normalization, short/blank names and rejection of unexpected fields).
- 3 authentication request-schema cases.
- 10 auth service/identity cases covering accepted verified identity claims, email normalization, unverified email rejection, missing UID, duplicate Firebase UID, rollback and profile membership behavior.

This run verifies these selected schema and authentication service tests. It does not include department service tests, database-backed department endpoint tests, frontend build/lint, live Firebase SMS delivery or deployment verification.

## External dependencies and safety

Some tests require PostgreSQL, Redis/Valkey, Qdrant, model credentials or OCR dependencies. Use isolated test services and test credentials. Do not run integration tests against production data. Verify organization/user identity and test data before running live E2E scripts.
