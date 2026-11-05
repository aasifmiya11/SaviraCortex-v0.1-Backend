# 21. Testing

## Framework and configuration

pytest is used. The project configures the repository root on the Python path, function-scoped asyncio fixtures, and an integration marker for tests that require external services.

## Test organization

- `tests/agent/`: agent behavior and structured-output tests.
- `tests/workflows/`: LangGraph node adapters, routing, and end-to-end graph tests.
- `tests/integration/`: indexing, summary-store, and retrieval integration.
- `tests/rag/` and `tests/rag/retrieval/`: dense, BM25/hybrid retrieval, fusion, reranking, adaptive-K, and candidate generation.
- `tests/rag/vector_stores/`: Qdrant payload-index behavior.
- `tests/services/`: ingestion, registration, indexing, lifecycle, and retrieval services.
- Root-level tests: authorization, repositories, PDF handling, hashing, normalization, and storage.

## Running tests

From the repository root:

```powershell
uv run pytest
```

Run the workflow suite:

```powershell
uv run pytest tests/workflows -v
```

Run a focused module:

```powershell
uv run pytest tests/workflows/test_graph.py -v
```

Run tests marked as integration:

```powershell
uv run pytest -m integration
```

Check the current test configuration and fixtures before relying on these commands in CI.

## External dependencies and safety

Some tests require PostgreSQL, Redis/Valkey, Qdrant, model credentials, or OCR dependencies. Use isolated test services and test credentials. Do not run integration tests against production data. The live E2E smoke-test script uses configured services and an explicitly selected organization/user identity; verify the tenant scope and test data before running it.

## Verification checkpoint — 5 November 2026

The user reported these local test results:

| Command | Result |
|---|---:|
| `uv run pytest tests/workflows -v` | 45 passed in 29.84s |
| `pytest -v` | 393 passed, 2 warnings in 163.43s |
| Retrieval exclusion focused suite | 49 passed in 92.79s |

The full-suite warnings were a LangChain community-package sunset/deprecation warning and a PyMuPDF `fitz` API deprecation warning. No test failures were reported.

These are user-reported local results. They are not CI results, production verification, or proof that all external-service behavior is reliable.

## End-to-end smoke testing

`scripts/workflow_E2E.py` exercises a simple query, a follow-up with conversation history, and whitespace-heavy input through the configured LangGraph workflow. It reports retrieval attempts, evidence counts, compression, generation status, citations, and Static Validation results.

A synthetic employee leave-policy PDF was ingested and indexed with nine Qdrant chunks. A run using the ingestion-created organization/user identity retrieved evidence and generated grounded answers for the first two scenarios. A later run using a different tenant identity had inconsistent evidence availability across scenarios. Treat this as an unresolved authorization/retrieval-scope investigation, not as proof of tenant isolation or a confirmed leak.

The script's current pass count indicates workflow completion/static validation under its own criteria; it does not assert that every response is fully answered or semantically correct.

See [Remaining implementation roadmap](28-remaining-implementation-roadmap.md) for evaluation and backend/frontend milestones.