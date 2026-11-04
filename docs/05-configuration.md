# 5. Configuration Guide

## 5.1 Loading behavior

`app/core/config.py` calls `load_dotenv()` and reads environment variables into a module-level `settings` object. Values are read when the module is imported. Changing environment variables after import does not automatically rebuild the settings object.

The helper `get_bool(name, default=False)` treats `true`, `1`, `yes`, and `on` (case-insensitive, trimmed) as true; other supplied values evaluate to false.

## 5.2 Environment variables

| Variable | Purpose | Default/notes |
|---|---|---|
| `OPENAI_BASE_URL` | Chat model API base URL | No default |
| `OPENAI_API_KEY` | Chat model credential | Secret; do not commit |
| `OPENAI_MODEL` | Chat model identifier | No default |
| `OCR_ENGINE` | OCR backend selector | No default |
| `OCR_LANGS` | OCR language configuration | No default |
| `RENDER_DPI` | PDF page render resolution for OCR | `300` |
| `MIN_NATIVE_CHARS` | Native text threshold used by OCR policy | `50` |
| `OCR_ALL_PAGES` | Force OCR for all pages when supported by policy | false |
| `OCR_MERGE_WITH_NATIVE` | Merge OCR and native extraction outputs | false |
| `FASTOCR_API_KEY` | FastOCR credential | Secret; optional unless selected |
| `QDRANT_API_KEY` | Qdrant credential | Secret |
| `QDRANT_API_ENDPOINT` | Qdrant endpoint | No default |
| `QDRANT_COLLECTION_NAME` | Chunk collection name | No default |
| `QDRANT_SUMMARY_COLLECTION_NAME` | Summary collection name | Defaults to `<chunk_collection>_summaries` when chunk name exists |
| `AIVEN_POSTGRES_URI` | PostgreSQL connection URI | Required when database module initializes |
| `AIVEN_REDIS_URI` | Redis-compatible connection URI | Required when Redis client is requested |
| `B2_KEY_ID` | Backblaze key ID | Secret |
| `B2_APPLICATION_KEY` | Backblaze application key | Secret |
| `B2_BUCKET_NAME` | Backblaze bucket | No default |
| `B2_REGION` | Backblaze region | No default |
| `B2_ENDPOINT_URL` | S3-compatible endpoint | No default |
| `B2_STORAGE_PREFIX` | Object key namespace | `voice-ai/` |

If `AIVEN_POSTGRES_URI` begins with `postgres://`, configuration rewrites that prefix to `postgresql+psycopg2://`.

## 5.3 Example environment template

Create a local `.env` file using values from your own service accounts. This template contains placeholders only:

```dotenv
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=

OCR_ENGINE=
OCR_LANGS=
RENDER_DPI=300
MIN_NATIVE_CHARS=50
OCR_ALL_PAGES=false
OCR_MERGE_WITH_NATIVE=false
FASTOCR_API_KEY=

QDRANT_API_KEY=
QDRANT_API_ENDPOINT=
QDRANT_COLLECTION_NAME=
QDRANT_SUMMARY_COLLECTION_NAME=

AIVEN_POSTGRES_URI=
AIVEN_REDIS_URI=

B2_KEY_ID=
B2_APPLICATION_KEY=
B2_BUCKET_NAME=
B2_REGION=
B2_ENDPOINT_URL=
B2_STORAGE_PREFIX=voice-ai/
```

## 5.4 Configuration safety

- Never put real API keys, database passwords, or service tokens in source control or documentation.
- Restrict credentials to the minimum required permissions.
- Keep separate credentials and endpoints for development, test and production.
- Do not share full connection URIs in logs or issue reports.
- Ensure OCR engine dependencies are installed on the host when that engine is selected.

## 5.5 Initialization requirements

The database module raises a `ValueError` if `AIVEN_POSTGRES_URI` is missing. The async Redis accessor raises a `RuntimeError` if `AIVEN_REDIS_URI` is missing. Other integrations may fail when first used if their settings or external credentials are absent.
