# 5. Configuration Guide

## Loading behavior

`app/core/config.py` calls `load_dotenv()` and builds a module-level `settings` object when imported. Environment changes made after import do not automatically rebuild that object.

The helper `get_bool(name, default=False)` treats `true`, `1`, `yes` and `on` (case-insensitive, trimmed) as true. Any other supplied value is false.

## Backend environment variables

| Variable | Purpose | Notes |
|---|---|---|
| `OPENAI_BASE_URL` | Chat model API base URL | Provider-dependent |
| `OPENAI_API_KEY` | Chat model credential | Secret |
| `OPENAI_MODEL` | Chat model identifier | Provider-dependent |
| `FIREBASE_PROJECT_ID` | Firebase Admin project ID | Must match the intended Firebase project |
| `FIREBASE_DATABASE_URL` | Optional Firebase database URL | Only needed where applicable |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Backend service-account JSON path | Defaults to `app/secrets/firebase-service-account.json`; secret file, never commit |
| `AIVEN_POSTGRES_URI` | PostgreSQL connection URI | Required when database module initializes |
| `AIVEN_REDIS_URI` | Redis-compatible connection URI | Required when Redis accessor is used |
| `QDRANT_API_KEY` | Qdrant credential | Secret |
| `QDRANT_API_ENDPOINT` | Qdrant endpoint | Required by Qdrant integrations |
| `QDRANT_COLLECTION_NAME` | Legacy/base chunk collection name | Used to derive the new Jina collection name unless an explicit Jina collection override is set |
| `QDRANT_SUMMARY_COLLECTION_NAME` | Legacy/base summary collection name | Used to derive the new Jina summary collection name unless an explicit Jina override is set |
| `JINA_API_KEY` | Jina API credential | Required for embedding and reranking; secret |
| `JINA_API_BASE_URL` | Jina API base URL | Defaults to `https://api.jina.ai/v1` |
| `JINA_EMBEDDING_MODEL` | Jina embedding model | Defaults to `jina-embeddings-v5-text-small` |
| `JINA_EMBEDDING_DIMENSIONS` | Embedding vector size | Defaults to 1024; must match the Jina model and Qdrant collection |
| `JINA_RERANKER_MODEL` | Jina reranker model | Defaults to `jina-reranker-v2-base-multilingual` |
| `JINA_API_TIMEOUT_SECONDS` | HTTP timeout for Jina requests | Defaults to 120 seconds |
| `JINA_EMBEDDING_BATCH_SIZE` | Number of passages per embedding request | Defaults to 64 |
| `JINA_QDRANT_COLLECTION_NAME` | New Jina chunk collection | Optional; default appends `_jina_v5_1024` to the legacy chunk collection name |
| `JINA_QDRANT_SUMMARY_COLLECTION_NAME` | New Jina summary collection | Optional; default appends `_jina_v5_1024` to the legacy summary collection name |
| `B2_KEY_ID` | Backblaze key ID | Secret |
| `B2_APPLICATION_KEY` | Backblaze application key | Secret |
| `B2_BUCKET_NAME` | Backblaze bucket | Environment-specific |
| `B2_REGION` | Backblaze region | Environment-specific |
| `B2_ENDPOINT_URL` | S3-compatible endpoint | Environment-specific |
| `B2_STORAGE_PREFIX` | Object key namespace | Defaults to `voice-ai/` |
| `RENDER_DPI` | PDF render resolution | Defaults to 300 |
| `MIN_NATIVE_CHARS` | Native text threshold | Defaults to 50 |
| `OCR_ALL_PAGES` | OCR every page | Defaults to false |
| `OCR_MERGE_WITH_NATIVE` | Merge OCR and native text | Defaults to false |
| `FASTOCR_API_KEY` | FastOCR credential | Required when a page needs OCR; secret |

Evaluation-specific settings are prefixed with `SAVIRACORTEX_EVAL_` and isolate evaluation organization/user IDs, Qdrant collections and B2 storage prefix from ordinary application resources.

If `AIVEN_POSTGRES_URI` begins with `postgres://`, configuration rewrites that prefix to `postgresql+psycopg2://`.

## Frontend environment variables

The browser Firebase SDK reads these public web-app configuration values:

- `NEXT_PUBLIC_FIREBASE_API_KEY`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
- `NEXT_PUBLIC_FIREBASE_APP_ID`
- Optional: `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`
- Optional: `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`
- Optional: `NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID`

The frontend API base URL is `NEXT_PUBLIC_API_BASE_URL`; the current pages default to `http://localhost:8000`.

Copy `frontend/firebase-config.example.txt` to `frontend/.env.local`, fill it with Firebase **web app** configuration, and restart Next.js. Firebase web configuration is intended to be public. Do not put the Admin SDK service-account JSON or private key in the frontend.

## Example backend environment template

Use placeholders only; do not copy real credentials into documentation:

```dotenv
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=

FIREBASE_PROJECT_ID=
FIREBASE_DATABASE_URL=
FIREBASE_SERVICE_ACCOUNT_PATH=app/secrets/firebase-service-account.json

AIVEN_POSTGRES_URI=
AIVEN_REDIS_URI=

QDRANT_API_KEY=
QDRANT_API_ENDPOINT=
QDRANT_COLLECTION_NAME=voiceai-local
QDRANT_SUMMARY_COLLECTION_NAME=voiceai-local_summaries

JINA_API_KEY=
JINA_API_BASE_URL=https://api.jina.ai/v1
JINA_EMBEDDING_MODEL=jina-embeddings-v5-text-small
JINA_EMBEDDING_DIMENSIONS=1024
JINA_RERANKER_MODEL=jina-reranker-v2-base-multilingual
JINA_API_TIMEOUT_SECONDS=120
JINA_EMBEDDING_BATCH_SIZE=64
# Optional overrides; otherwise a _jina_v5_1024 suffix is added.
JINA_QDRANT_COLLECTION_NAME=
JINA_QDRANT_SUMMARY_COLLECTION_NAME=

B2_KEY_ID=
B2_APPLICATION_KEY=
B2_BUCKET_NAME=
B2_REGION=
B2_ENDPOINT_URL=
B2_STORAGE_PREFIX=

RENDER_DPI=300
MIN_NATIVE_CHARS=50
OCR_ALL_PAGES=false
OCR_MERGE_WITH_NATIVE=false
FASTOCR_API_KEY=
```

## Configuration safety

- Never commit real API keys, database passwords, Firebase service-account files or service tokens.
- Keep separate credentials and endpoints for development, test and production.
- Restrict credentials to minimum required permissions.
- Do not log complete connection URIs, tokens or private keys.
- Real Firebase SMS delivery requires the appropriate Firebase billing/project configuration; test phone numbers are suitable for development but do not prove production SMS readiness.


## Cloudflare Qwen3 embeddings

The backend supports `EMBEDDING_PROVIDER=jina` (default) or `EMBEDDING_PROVIDER=cloudflare`. Cloudflare uses the gateway client credential in the existing backend-only `JINA_API_KEY` setting and calls `/v1/cloudflare/embeddings`. Keep Cloudflare provider account IDs and tokens only in `api-gateway/.env`, configured as equal-length parallel JSON arrays.

Defaults:
- Model: `@cf/qwen/qwen3-embedding-0.6b`
- Dimensions: `1024`
- Gateway model setting: `CLOUDFLARE_EMBEDDING_MODEL`
- Backend selector: `EMBEDDING_PROVIDER=cloudflare`
- Backend vector dimension setting: `CLOUDFLARE_EMBEDDING_DIMENSIONS=1024`

Cloudflare and Jina vectors must never share a Qdrant collection. The Cloudflare chunk and summary collections are derived with the `_cloudflare_qwen3_1024` suffix or can be explicitly set with `CLOUDFLARE_QDRANT_COLLECTION_NAME` and `CLOUDFLARE_QDRANT_SUMMARY_COLLECTION_NAME`. Switching providers selects the corresponding pair of collections; it does not migrate existing vectors. Re-embed and re-index documents before relying on the Cloudflare collections for retrieval.
