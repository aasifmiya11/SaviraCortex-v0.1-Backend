# 4. Project Structure

**Repository root:** `E:\\SaviraCortex`

## 4.1 Repository map

```text
SaviraCortex/
├── backend/
│   ├── app/
│   │   ├── agents/                 # LLM agents and prompts
│   │   ├── api/v1/
│   │   │   ├── endpoints/          # auth, departments, health, home
│   │   │   └── router.py
│   │   ├── core/                   # settings, database, Firebase, dependencies
│   │   ├── llm/                    # model clients
│   │   ├── models/                 # SQLAlchemy entities
│   │   ├── rag/                    # PDF, ingestion, retrieval, vectors
│   │   ├── repositories/           # database access
│   │   ├── schemas/v1/             # auth and department contracts
│   │   ├── services/
│   │   │   ├── auth/
│   │   │   ├── authorization/
│   │   │   ├── department_service.py
│   │   │   ├── document_indexing/
│   │   │   ├── document_ingestion/
│   │   │   ├── document_matching/
│   │   │   ├── document_registration/
│   │   │   └── retrieval/
│   │   ├── storage/
│   │   ├── validation/
│   │   └── workflows/rag/
│   ├── docs/                       # numbered technical documentation
│   ├── evals/                      # evaluation assets and plans
│   ├── migrations/
│   ├── scripts/
│   ├── tests/
│   ├── app/main.py                 # FastAPI entry point
│   ├── pyproject.toml
│   └── uv.lock
└── frontend/
    ├── src/app/
    │   ├── page.tsx                # public homepage
    │   ├── login/page.tsx
    │   ├── register/page.tsx
    │   ├── dashboard/page.tsx
    │   └── firebase.ts
    ├── public/
    ├── package.json
    └── package-lock.json
```

This is a high-level map, not an exhaustive file listing. Preserve existing package capitalization and naming conventions when importing modules.

## 4.2 Backend package responsibilities

- `app/api/v1/endpoints`: HTTP route declarations for authentication, departments, health and home.
- `app/api/v1/router.py`: versioned API router composition.
- `app/core`: configuration, database session lifecycle, Firebase Admin setup and FastAPI dependencies.
- `app/schemas/v1`: Pydantic request/response contracts.
- `app/models`: SQLAlchemy database entities.
- `app/repositories`: relational queries and persistence operations.
- `app/services/auth`: organization signup and authenticated identity/profile resolution.
- `app/services/department_service.py`: organization-scoped department authorization and creation.
- `app/services/authorization`: document-level access calculations and related cache helper.
- `app/services/document_ingestion`, `document_registration`, `document_indexing`: document lifecycle services.
- `app/services/retrieval` and `app/rag/retrieval`: retrieval orchestration and retrieval algorithms.
- `app/agents` and `app/workflows/rag`: LLM agents and end-to-end RAG graph.
- `app/validation`: deterministic output/citation validation.
- `app/storage`: object-storage abstraction.

## 4.3 Frontend routes

| Route | Purpose |
|---|---|
| `/` | SaviraCortex public homepage |
| `/login` | Firebase sign-in UI |
| `/register` | Firebase identity registration and organization signup |
| `/dashboard` | Authenticated organization overview and department management |

The dashboard consumes `GET /api/v1/auth/me` and organization-specific department endpoints. Firebase remains the browser-side identity SDK; backend API requests carry Firebase ID tokens.

## 4.4 Documentation

Technical documentation lives in `backend/docs/`. The numbered documents cover the system from project overview through context compression. The latest application/authentication checkpoint is [30-current-application-checkpoint.md](30-current-application-checkpoint.md). Update the relevant architecture, schema, authorization and testing pages when implementation changes.
