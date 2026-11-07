# 4. Project Structure

**Repository root:** `E:\SaviraCortex`

## 4.1 Repository map

```text
SaviraCortex/
├── README.md
├── backend/
│   ├── app/
│   │   ├── agents/                 # LLM agents and prompts
│   │   ├── api/v1/endpoints/       # FastAPI route modules
│   │   ├── core/                  # Settings, DB, Firebase, dependencies
│   │   ├── guardrails/             # Input/output guardrail components
│   │   ├── llm/                    # Model/provider clients
│   │   ├── memory/                 # Memory-related components
│   │   ├── models/                 # SQLAlchemy entities
│   │   ├── rag/                    # PDF, chunking, embeddings, retrieval, vectors
│   │   ├── repositories/           # Relational persistence
│   │   ├── schemas/v1/             # API contracts
│   │   ├── services/               # Domain and workflow services
│   │   ├── storage/                # B2/S3-compatible file storage
│   │   ├── validation/             # Output/citation validation
│   │   └── workflows/rag/          # LangGraph generation workflow
│   ├── docs/                       # Numbered technical documentation
│   ├── evals/                      # Golden synthesis and evaluation
│   ├── scripts/                    # Setup and operational scripts
│   ├── tests/                      # Unit, service, workflow, integration tests
│   ├── pyproject.toml
│   └── uv.lock
└── frontend/
    ├── src/app/
    │   ├── dashboard/              # Dashboard, ingestion, library, chat
    │   ├── invitations/            # Invitation acceptance
    │   ├── login/
    │   ├── register/
    │   ├── signup/
    │   ├── page.tsx                # Public homepage
    │   └── firebase.ts             # Browser Firebase configuration
    ├── public/
    ├── package.json
    └── package-lock.json
```

This is a high-level map, not an exhaustive file listing. Ignore generated directories such as `.venv`, `node_modules`, `.next`, `__pycache__` and test caches when reasoning about source structure.

## 4.2 Backend package responsibilities

- `app/api/v1/endpoints`: authentication, organization, membership, invitation, ingestion, document-library and generation HTTP routes.
- `app/api/v1/router.py`: versioned API router composition.
- `app/core`: configuration, database sessions, Firebase Admin and FastAPI dependencies.
- `app/schemas/v1`: Pydantic request/response contracts.
- `app/models`: SQLAlchemy database entities.
- `app/repositories`: relational queries and persistence operations.
- `app/services/auth`: signup and authenticated identity/profile resolution.
- `app/services/authorization`: document-level access decisions.
- `app/services/document_ingestion`: PDF analysis and ingestion orchestration.
- `app/services/document_registration`: logical document and version registration.
- `app/services/document_indexing`: chunk/vector indexing and activation lifecycle.
- `app/services/document_management`: document metadata, version summaries and deletion.
- `app/services/retrieval` and `app/rag/retrieval`: retrieval orchestration and algorithms.
- `app/agents`, `app/llm` and `app/workflows/rag`: agents, model adapters and end-to-end RAG graph.
- `app/validation`: deterministic output/citation validation.
- `app/storage`: B2/S3-compatible object operations.
- `evals`: dataset synthesis and evaluation entry points.

## 4.3 Frontend routes and components

| Route/component | Purpose |
|---|---|
| `/` | Public homepage |
| `/login` | Firebase sign-in |
| `/register` | Firebase registration and organization onboarding |
| `/signup` | Additional signup route |
| `/dashboard` | Organization workspace and administration |
| `/dashboard/chat` | RAG chat UI |
| `/invitations/accept` | Invitation acceptance |
| `dashboard/DocumentIngestionModal.tsx` | PDF ingestion UI |
| `dashboard/DocumentLibrary.tsx` | Document list, detail and lifecycle UI |
| `dashboard/InvitationPanel.tsx` | Organization invitation UI |
| `BatchIngestionWidget.tsx` | Batch upload/progress presentation |

## 4.4 Documentation

Project entry point: repository-root `README.md`. Detailed technical documentation lives in `backend/docs/`. The current project-wide checkpoint is [31-project-wide-current-state.md](31-project-wide-current-state.md). Update relevant subsystem pages and the checkpoint when implementation changes.
