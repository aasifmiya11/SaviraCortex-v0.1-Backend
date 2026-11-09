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

## Embedding provider configuration

The backend routes embeddings through the standalone API gateway. Jina remains the default provider. To use Cloudflare Qwen3 embeddings instead, set this in `backend/.env`:

```dotenv
JINA_API_BASE_URL=http://127.0.0.1:8090/v1
JINA_API_KEY=<copy the gateway GATEWAY_API_KEY into this backend-only variable>
EMBEDDING_PROVIDER=cloudflare
CLOUDFLARE_EMBEDDING_MODEL=@cf/qwen/qwen3-embedding-0.6b
CLOUDFLARE_EMBEDDING_DIMENSIONS=1024
```

Set `EMBEDDING_PROVIDER=jina` (or omit it) to retain the existing Jina integration. The backend gateway key is the client credential, not a provider API key. Cloudflare account IDs and provider tokens remain exclusively in `api-gateway/.env`; the gateway rotates the paired account/token entries and fails over on transient/provider errors.

**Qdrant isolation:** the selected provider automatically uses its own collection names. Jina keeps the `_jina_v5_1024` suffix; Cloudflare uses `_cloudflare_qwen3_1024`. You can override them with `JINA_QDRANT_COLLECTION_NAME`, `JINA_QDRANT_SUMMARY_COLLECTION_NAME`, `CLOUDFLARE_QDRANT_COLLECTION_NAME`, and `CLOUDFLARE_QDRANT_SUMMARY_COLLECTION_NAME`. Never point both models at the same collection. Switching providers requires re-embedding/re-indexing documents into the selected provider's collections; existing Jina vectors are not converted or deleted.

The code defaults to the local gateway URL if `JINA_API_BASE_URL` is omitted. Firebase Admin uses the backend-only service-account JSON configured by `FIREBASE_SERVICE_ACCOUNT_PATH` (default: `app/secrets/firebase-service-account.json`). Never commit credential files.

## RAG feedback dataset

Every validated answer, multi-query trace, selected document chunk, and final Markdown response is stored in PostgreSQL with an initially empty relevance label. The chat UI records **Relevant / Not relevant** feedback. The organization-scoped labeled dataset is available through GET /api/v1/organizations/{organization_id}/generation/feedback-dataset. See [RAG feedback dataset](docs/22-rag-feedback-dataset.md) and apply migrations/0001_generation_feedback.sql (or run python -m scripts.create_generation_feedback_table) before deployment.

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
