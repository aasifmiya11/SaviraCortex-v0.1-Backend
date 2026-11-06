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
| `QDRANT_COLLECTION_NAME` | Chunk collection | Environment-specific |
| `QDRANT_SUMMARY_COLLECTION_NAME` | Summary collection | Defaults to chunk collection plus `_summaries` |
| `B2_KEY_ID` | Backblaze key ID | Secret |
| `B2_APPLICATION_KEY` | Backblaze application key | Secret |
| `B2_BUCKET_NAME` | Backblaze bucket | Environment-specific |
| `B2_REGION` | Backblaze region | Environment-specific |
| `B2_ENDPOINT_URL` | S3-compatible endpoint | Environment-specific |
| `B2_STORAGE_PREFIX` | Object key namespace | Defaults to `voice-ai/` |
| `OCR_ENGINE` | OCR backend selector | Loader supports EasyOCR, Tesseract or FastOCR |
| `OCR_LANGS` | OCR languages | Loader default is English |
| `RENDER_DPI` | PDF render resolution | Defaults to 300 |
| `MIN_NATIVE_CHARS` | Native text threshold | Defaults to 50 |
| `OCR_ALL_PAGES` | OCR every page | Defaults to false |
| `OCR_MERGE_WITH_NATIVE` | Merge OCR and native text | Defaults to false |
| `FASTOCR_API_KEY` | FastOCR credential | Required only when selected |

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
QDRANT_COLLECTION_NAME=
QDRANT_SUMMARY_COLLECTION_NAME=

B2_KEY_ID=
B2_APPLICATION_KEY=
B2_BUCKET_NAME=
B2_REGION=
B2_ENDPOINT_URL=
B2_STORAGE_PREFIX=

OCR_ENGINE=easyocr
OCR_LANGS=en
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
