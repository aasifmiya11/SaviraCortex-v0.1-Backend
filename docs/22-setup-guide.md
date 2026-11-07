# 22. Local Setup Guide

## Prerequisites

- Python 3.11 or newer.
- `uv` (recommended; the repository includes `uv.lock`).
- Node.js and npm compatible with the Next.js version in `frontend/package.json`.
- A configured PostgreSQL database.
- Firebase project with the required Authentication providers.
- Qdrant and Backblaze B2 credentials for document ingestion/indexing and retrieval.
- Redis-compatible service where cache functionality is used.
- LLM provider credentials and the OCR system dependencies/language data required by the selected PDF loader.

## Backend setup

From `E:\SaviraCortex\backend`:

```powershell
uv sync
```

Create a local `.env` using [05 — Configuration](05-configuration.md). Fill credentials locally; do not commit the file. The backend configuration is loaded when `app/core/config.py` is imported.

Start the API:

```powershell
uv run uvicorn app.main:app --reload
```

The API documentation is at `http://localhost:8000/api/v1/docs`.

## Frontend setup

1. Create a Firebase Web app in the same Firebase project used by the backend Admin SDK.
2. Enable the providers used by the app: Email/Password, Google and Phone.
3. Copy `frontend/firebase-config.example.txt` to `frontend/.env.local`.
4. Populate the `NEXT_PUBLIC_FIREBASE_*` values from Firebase Web app configuration.
5. Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` (or the intended backend URL).
6. From `frontend/`, run:

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`. Restart Next.js after changing `.env.local`.

Never put the Firebase Admin service-account JSON or private key in frontend configuration.

## Database schema safety

The SQLAlchemy helper `Base.metadata.create_all()` creates missing registered tables only; it does not modify existing table definitions. The repository's reset scripts may be destructive. Do not run a reset script unless the target is confirmed to be a disposable/empty development database and the project owner explicitly approves the reset.

The project owner has instructed that migrations should not be introduced without approval. If a feature needs schema changes, update models and model registration, explain the impact, and ask the owner to reset the empty development database. Do not perform the reset automatically.

## Verify setup

1. Confirm Python/uv and Node/npm versions.
2. Confirm the backend `.env` points to the intended database and external services.
3. Confirm Firebase Admin project ID and service-account project match the Firebase Web app project.
4. Confirm Qdrant collections and credentials.
5. Confirm B2 bucket permissions.
6. Confirm OCR engine and language packs.
7. Start backend and frontend in separate terminals.
8. Open API docs and verify the health endpoint.
9. Run focused tests before exercising workflows that use external services.

Real Firebase SMS delivery requires the appropriate billing configuration. Firebase test phone numbers do not prove live SMS readiness.
