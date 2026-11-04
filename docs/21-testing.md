# 21. Testing

## Framework and configuration

pytest is used. `pyproject.toml` adds the repository root to `pythonpath`, sets the asyncio fixture loop scope to function, and declares an `integration` marker for tests requiring external services/integration infrastructure.

## Test organization

- `tests/agent/`: summarizer and multi-query agent tests.
- `tests/integration/`: indexing concurrency, summary store and retrieval integration.
- `tests/rag/`: dense, hybrid and BM25 retrieval.
- `tests/rag/retrieval/`: adaptive-k, candidate generation, candidate-scoped retrieval, reranking and global fusion.
- `tests/rag/vector_stores/`: Qdrant payload indexes.
- `tests/services/`: ingestion, matching, registration, indexing, lifecycle and retrieval service behavior.
- Root-level tests: authorization, repositories, PDF handling, hashing, normalization and storage.

## Running tests

From the repository root:

```bash
pytest
```

Run a focused module:

```bash
pytest tests/services/test_document_ingestion.py
```

Select integration tests:

```bash
pytest -m integration
```

Check available markers and fixtures in the current test configuration before relying on these commands in CI.

## External dependencies

Some tests may require PostgreSQL, Redis/Valkey, Qdrant, model credentials or OCR dependencies. Use isolated test services and test credentials. Do not run integration tests against production data.

## Review status

The audit inspected the test inventory and relevant tests for authorization, PDF processing, agents, matching, registration, indexing, retrieval, storage and reconciliation. On 4 November 2026, the user reported a passing focused run of `tests/agent/test_generation.py` and `tests/agent/test_generation_validation.py`: **17 passed in 6.14 seconds**. The full test suite was not executed, so no full-suite pass/fail claim is made. See [Remaining implementation roadmap](28-remaining-implementation-roadmap.md) for the next integration testing milestones.
