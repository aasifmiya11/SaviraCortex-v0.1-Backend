# 5. Configuration Guide

## 5.1 Loading behavior

`app/core/config.py` calls `load_dotenv()` and builds a module-level `settings` object when the module is imported. Environment changes made after import do not automatically rebuild that object.

The helper `get_bool(name, default=False)` treats `true`, `1`, `yes`, and `on` (case-insensitive, trimmed) as true. Any other supplied value is false.

## 5.2 Environment variables

| Variable | Purpose | Default/notes |
|---|---|---|
| `OPENAI_BASE_URL` | Chat model API base URL | No default |
| `OPENAI_API_KEY` | Chat model credential | Secret; do not commit |
| `OPENAI_MODEL` | Chat model identifier | No default |
| `OCR_ENGINE` | OCR backend selector | Loader defaults to `easyocr` |
| `OCR_LANGS` | OCR language configuration | Loader defaults to `en` |
| `RENDER_DPI` | PDF page render resolution for OCR | `300` |
| `MIN_NATIVE_CHARS` | Native text threshold used by OCR policy | `50` |
| `OCR_ALL_PAGES` | Attempt OCR on every page | false |
| `OCR_MERGE_WITH_NATIVE` | Permit usable OCR text to be merged with native text | false |
| `FASTOCR_API_KEY` | FastOCR credential | Used when FastOCR is selected |
| `QDRANT_API_KEY` | Qdrant credential | Secret |
| `QDRANT_API_ENDPOINT` | Qdrant endpoint | No default |
| `QDRANT_COLLECTION_NAME` | Chunk collection name | No default |
| `QDRANT_SUMMARY_COLLECTION_NAME` | Summary collection name | Defaults to `<chunk_collection>_summaries` when chunk name exists |
| `AIVEN_POSTGRES_URI` | PostgreSQL connection URI | Required when database module initializes |
| `AIVEN_REDIS_URI` | Redis-compatible connection URI | Required when `get_redis()` is called |
| `B2_KEY_ID` | Backblaze key ID | Secret |
| `B2_APPLICATION_KEY` | Backblaze application key | Secret |
| `B2_BUCKET_NAME` | Backblaze bucket | No default |
| `B2_REGION` | Backblaze region | No default |
| `B2_ENDPOINT_URL` | S3-compatible endpoint | No default |
| `B2_STORAGE_PREFIX` | Object key namespace | `voice-ai/` |

If `AIVEN_POSTGRES_URI` begins with `postgres://`, configuration rewrites that prefix to `postgresql+psycopg2://`.

The PDF loader accepts `easyocr`, `tesseract`, or `fastocr`. Its language defaults are `en`; the Tesseract adapter maps common language codes (for example `en` to `eng`).

## 5.3 Example environment template

Create a local `.env` file using values from your own service accounts. This template contains placeholders only:

```dotenv
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=

OCR_ENGINE=easyocr
OCR_LANGS=en
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
- Ensure OCR engine dependencies and language data are installed on the host when that engine is selected.

## 5.5 Initialization requirements

The database module raises a `ValueError` if `AIVEN_POSTGRES_URI` is missing during module initialization. The async Redis accessor raises a `RuntimeError` if `AIVEN_REDIS_URI` is missing. B2 settings are validated lazily when its client/bucket helpers are used. Qdrant and model integrations also require valid endpoint/model credentials when initialized or invoked.
