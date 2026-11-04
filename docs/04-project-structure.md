# 4. Project Structure

## 4.1 Repository map

```text
Voice-AI/
├── app/
│   ├── agents/
│   │   ├── Document_summarizer/
│   │   ├── Multi_query_generator/
│   │   └── Generation/
│   ├── api/v1/                 # empty in reviewed tree
│   ├── core/                   # settings, database, Redis
│   ├── guardrails/             # empty
│   ├── llm/                    # model clients, including generator_client.py
│   ├── memory/                 # empty
│   ├── models/                 # SQLAlchemy entities
│   ├── observability/          # empty
│   ├── rag/
│   │   ├── embeddings/
│   │   ├── ingestion/
│   │   ├── pdf_reader/
│   │   ├── retrieval/
│   │   ├── splitters/
│   │   └── vector_stores/
│   ├── repositories/
│   ├── schemas/                # empty
│   ├── validation/             # deterministic generation-output validation and citation metadata mapping
│   ├── services/
│   │   ├── authorization/
│   │   ├── document_indexing/
│   │   ├── document_ingestion/
│   │   ├── document_matching/
│   │   ├── document_registration/
│   │   └── retrieval/
│   ├── storage/
│   ├── tasks/                  # empty
│   ├── tools/                  # empty
│   └── utils/                  # empty
├── data/                       # local fixtures/artifacts
├── migrations/                 # empty
├── scripts/
├── tests/
├── main.py
├── storage.py
├── pyproject.toml
├── uv.lock
└── README.md
```

## 4.2 Package responsibilities

- `app/agents`: document summarization (prompt/model/parser chain), multi-query generation (one-node LangGraph), and company-grounded answer generation (prompt/model/parser chain), with prompts, configuration and Pydantic schemas. See [Generation pipeline](26-generation-pipeline.md).
- `app/api`: reserved API namespace; no endpoints were found. The current validation layer does not add HTTP routes.
- `app/validation`: deterministic validation of Generation output and request-scoped citation metadata mapping. See [Static validation](27-static-validation.md).
- `app/core`: global settings, SQLAlchemy engine/session lifecycle and async Redis client.
- `app/llm`: provider-specific chat model factories.
- `app/models`: relational entity definitions.
- `app/rag`: PDF extraction, embeddings, chunking, retrieval algorithms and Qdrant adapters.
- `app/repositories`: database query and persistence operations.
- `app/services`: business workflows and orchestration.
- `app/storage`: Backblaze B2/S3 object storage abstraction.
- `scripts`: direct operational and diagnostic entry points.
- `tests`: behavior verification by component and integration boundary.

## 4.3 Root-level files

- `main.py`: minimal greeting function; not the service runtime.
- `app/main.py`: currently a placeholder print statement.
- `storage.py`: separate root-level storage implementation; inspect before treating it as the same abstraction as `app/storage/`.
- `pyproject.toml`: package metadata and dependencies.
- `uv.lock`: resolved dependency lock.
- `README.md`: currently contains only a short HTML comment, not setup documentation.
- `data/`: includes sample PDF files and a SQLite database artifact.

## 4.4 Naming note

Some package/file names use capitalization or spelling that should be preserved when importing, such as `Document_summarizer`, `Multi_query_generator`, and `recurrsive_text_splitter.py`. This document intentionally records the current paths rather than proposing renames.
