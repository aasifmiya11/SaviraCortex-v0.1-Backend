# 4. Project Structure

## 4.1 Repository map

```text
Voice-AI/
├── app/
│   ├── agents/
│   │   ├── Document_summarizer/
│   │   └── Multi_query_generator/
│   ├── api/v1/                 # empty in reviewed tree
│   ├── core/                   # settings, database, Redis
│   ├── guardrails/             # empty
│   ├── llm/                    # model client factories
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

- `app/agents`: document summarization (prompt/model/parser chain) and multi-query generation (one-node LangGraph), with prompts, configuration and Pydantic schemas.
- `app/api`: reserved API namespace; no endpoints were found.
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
