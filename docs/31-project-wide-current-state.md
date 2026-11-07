# 31. Project-Wide Current State

**Checkpoint:** 7 November 2026
**Scope:** Backend, frontend, identity, organization administration, document lifecycle, RAG, evaluation and local development.

This document supersedes the older application snapshot where it conflicts with the current source. It is a source-oriented engineering checkpoint, not a claim that every feature has passed integration testing or is deployed. The source tree is authoritative.

## 31.1 Product summary

SaviraCortex is a multi-tenant document intelligence and RAG application. An organization can manage members, roles and departments; ingest and version PDF documents; control access to documents; and ask questions answered from authorized indexed evidence.

The platform is composed of:
- A Next.js App Router frontend.
- A FastAPI backend with a versioned `/api/v1` API.
- Firebase Authentication for external identity.
- PostgreSQL/SQLAlchemy for application records and tenant relationships.
- Backblaze B2 (S3-compatible) for original PDF objects.
- Qdrant for chunk and document-summary vector collections.
- A Redis-compatible service for cache functionality.
- An LLM provider and embedding/OCR components for document processing and generation.
- LangGraph-based RAG orchestration and deterministic answer/citation validation.

## 31.2 Current user-facing application

Frontend routes found in `frontend/src/app`:

| Route | Purpose |
|---|---|
| `/` | Public product homepage |
| `/login` | Firebase Email/Password, Google and Phone sign-in |
| `/register` | Firebase identity registration and organization onboarding |
| `/signup` | Additional signup route; inspect current page implementation before changing its behavior |
| `/dashboard` | Authenticated organization workspace |
| `/dashboard/chat` | Chat interface for organization-grounded generation |
| `/invitations/accept` | Invitation acceptance flow |

The dashboard currently composes organization context, custom roles, organization members, departments and department assignments, invitations, document ingestion and document library components. The document library supports search/listing, detail/version history, metadata and summary updates, archive/restore, superseding a document with a new version, and permanent deletion.

The ingestion UI includes a batch ingestion widget. Its in-browser progress state is presentation state; it should not be described as a durable server-side job queue.

## 31.3 Backend architecture

The FastAPI application is created in `app/main.py`. The API router is mounted at `/api/v1`. Swagger, ReDoc and OpenAPI are exposed at:
- `/api/v1/docs`
- `/api/v1/redoc`
- `/api/v1/openapi.json`

The backend is layered:

| Layer | Main location | Responsibility |
|---|---|---|
| HTTP/API | `app/api/v1/endpoints` | Request handling, dependencies and HTTP responses |
| Contracts | `app/schemas/v1` | Pydantic request/response validation |
| Domain services | `app/services` | Authorization, workflows, transactions and orchestration |
| Persistence | `app/models`, `app/repositories` | SQLAlchemy entities and relational queries |
| RAG components | `app/rag`, `app/workflows/rag` | PDF processing, chunking, embeddings, retrieval and graph orchestration |
| Agents/LLM | `app/agents`, `app/llm` | Model calls, prompts and structured generation |
| Storage | `app/storage` | B2/S3-compatible file operations |
| Runtime | `app/core` | Settings, database sessions, Firebase and dependencies |
| Evaluation | `evals/` | Dataset synthesis and evaluation runners |

Endpoints should remain thin. Domain rules belong in services; relational query behavior belongs in repositories; request/response contracts belong in schemas.

## 31.4 API surface

All routes below are mounted under `/api/v1`. This is a route-family index; the live OpenAPI document and endpoint modules define the exact parameters, request schemas, response schemas and status codes.

| Area | Route family | Main operations |
|---|---|---|
| Home/health | `/`, `/health` | API home and health check |
| Authentication | `/auth/me`, `/auth/organizations/signup` | Current identity/profile and initial organization signup |
| Organizations | `/organizations` | Create, list, get and update organizations |
| Organization roles | `/organizations/{organization_id}/roles` | List and create custom roles |
| Organization members | `/organizations/{organization_id}/members` | List/add/update/remove members and assign custom roles |
| Departments | `/organizations/{organization_id}/departments` | List and create departments |
| Department members | `/organizations/{organization_id}/departments/{department_id}/members` | List, assign and remove department members |
| Invitations | `/organizations/{organization_id}/invitations`, `/invitations/*` | Create/list invitations, preview and accept |
| Document ingestion | `/organizations/{organization_id}/documents/ingestion-sessions/*` | Analyze/stage, finalize and stream progress |
| Batch ingestion | `/organizations/{organization_id}/documents/ingestion-batches/stream` | Stream progress for a batch of PDF files |
| Indexing retry | `/organizations/{organization_id}/documents/versions/{document_version_id}/index` | Retry indexing a pending version |
| Document library | `/organizations/{organization_id}/documents` | List/detail, update metadata/archive state, update version summary, permanently delete |
| Generation | `/organizations/{organization_id}/generation` | Generate a validated answer or stream answer events |

Generation also exposes `POST /organizations/{organization_id}/generation/stream` and returns Server-Sent Events. Both generation routes require a verified Firebase identity and organization membership.

Document-library routes currently include:
- `GET /organizations/{organization_id}/documents`
- `GET /organizations/{organization_id}/documents/{document_id}`
- `PATCH /organizations/{organization_id}/documents/{document_id}`
- `PATCH /organizations/{organization_id}/documents/{document_id}/versions/{version_id}`
- `DELETE /organizations/{organization_id}/documents/{document_id}`

## 31.5 Identity, tenant isolation and authorization

Firebase is the identity provider, not the application authorization database.

1. The browser authenticates using Firebase and obtains an ID token.
2. API calls send the token as `Authorization: Bearer <Firebase ID token>`.
3. Firebase Admin verifies the token.
4. Backend services map the verified Firebase UID to a SaviraCortex user.
5. Organization-scoped operations verify the user's membership and required role.
6. Document retrieval/management additionally applies document access rules and organization scope.

Never trust a client-supplied user ID, organization ID, role or department assignment as proof of permission. UI visibility is not an authorization boundary. Qdrant payload filters and vector similarity do not replace relational authorization checks.

Firebase Admin configuration and browser Firebase configuration are separate. The service-account JSON and all server credentials must remain private. Real SMS OTP delivery requires the appropriate Firebase billing/project configuration; Firebase test phone numbers only verify the development test path.

## 31.6 Organization and access-control domain

The relational model set includes users, organizations, organization memberships, organization roles, user-role assignments, departments and department memberships. Organization invitations are also persisted.

Organization-level roles govern administrative operations. Custom roles can be assigned to members. Department membership records associate users with departments. Document ACL records represent document-specific access policy principals.

Exact role semantics and permission resolution must be read from the current service implementation and [07 — Authorization](07-authorization.md); do not infer that every custom role automatically has the same privileges as the built-in owner/admin roles.

## 31.7 Document ingestion and lifecycle

The current ingestion API supports a staged flow and streaming upload/analysis flow. The pipeline includes:
1. Validate uploaded PDF and enforce file/input constraints.
2. Extract native text and use OCR when needed.
3. Normalize extracted text while retaining page-oriented information.
4. Calculate hashes and compare against existing documents/versions.
5. Generate document summary and resolve metadata.
6. Register the logical document/version and store the source PDF in B2.
7. Chunk content, generate embeddings and write chunk/search payloads to Qdrant.
8. Index document/version summaries in the summary collection.
9. Activate the version only after successful indexing; failed indexing remains retryable.

The batch ingestion widget reports per-file progress in the browser. Do not confuse this with a durable distributed job system.

## 31.8 Document library and deletion

The current document library API and dashboard component provide:
- Organization-scoped document listing and search.
- Document detail and version history.
- Metadata editing.
- Archive and restore.
- Version-summary editing with summary-vector synchronization.
- Superseding an existing logical document by uploading a replacement version through ingestion.
- Permanent deletion by document ID.

Permanent deletion spans multiple systems: relational document/version/ACL data, source objects in B2, chunk/BM25 points and summary vectors in Qdrant. These systems do not share a distributed transaction. The deletion service attempts external cleanup before committing relational deletion; failures must leave enough relational state to retry cleanup. Deletion should be treated as idempotent and retried after correcting an external-store failure.

Qdrant deletion filters depend on payload indexes. The current vector-store code adds a root-level `document_id` keyword index for the chunk and summary collections. Existing collections need to run the current initialization path so missing indexes are created.

## 31.9 Retrieval and answer generation

The RAG system is modular. Its documented retrieval path includes candidate generation using dense and lexical signals, fusion, reranking and adaptive top-K selection. Authorization filtering is part of retrieval and must remain organization/user scoped.

The LangGraph generation workflow coordinates:
- Query and input validation.
- Authorized retrieval.
- Evidence sufficiency evaluation.
- Bounded retrieval expansion when evidence is insufficient.
- Conditional context compression.
- LLM answer generation with structured output.
- Static validation and request-scoped citation checks.

The non-streaming API returns a validated response object. The streaming API emits SSE events, including status/progress, generated events and safe error events. Conversation history is accepted in the generation request, but the existence of this request field does not imply persistent server-side conversation storage.

The chat UI/API is present; persistent conversation history and management should be documented as separate capability until database-backed conversation records are implemented.

## 31.10 Data stores and model inventory

The current SQLAlchemy model package exports:
- `User`
- `Organization`
- `OrganizationDepartment`
- `OrganizationMembership`
- `OrganizationDepartmentMembership`
- `Document`
- `DocumentVersion`
- `OrganizationRole`
- `UserRoleAssignment`
- `DocumentACL`
- `OrganizationInvitation`
- `DocumentIngestionSession`

PostgreSQL is the authoritative relational store. Backblaze B2 stores source files. Qdrant stores vectorized document chunks and summaries. Redis-compatible infrastructure supports cache functionality. Firebase manages external identity.

The database helper's `create_tables()` uses `Base.metadata.create_all` after importing models. This creates missing registered tables; it does not alter existing table definitions. The repository's reset scripts may be destructive. Do not run them casually. If a future code change requires schema changes, follow the project owner's instruction to update models/registration and explicitly request a database reset only after explaining the requirement; do not introduce migrations without approval.

## 31.11 Evaluation assets

The repository contains:
- `evals/dataset_synthesizer/` — document preprocessing, custom LLM/embedding adapters and golden generation.
- `evals/datasets/` — generated dataset artifacts and metadata.
- `evals/evaluate.py` and `evals/ingestion_evaluation.py` — evaluation entry points.
- `evals/results/` — recorded evaluation output.

Keep generated datasets/results distinct from source corpus files. Evaluation resources must use isolated organization/user IDs, vector collections and object-storage prefixes; never run destructive evaluation cleanup against ordinary application data.

## 31.12 Local development

Backend:

```powershell
cd E:\SaviraCortex\backend
uv sync
uv run uvicorn app.main:app --reload
```

Frontend in another terminal:

```powershell
cd E:\SaviraCortex\frontend
npm install
npm run dev
```

Useful URLs:
- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/api/v1/docs`
- OpenAPI: `http://localhost:8000/api/v1/openapi.json`

Backend focused tests:

```powershell
cd E:\SaviraCortex\backend
uv run pytest tests/test_v1_documents_endpoints.py tests/services/test_document_deletion.py -v
```

The command above is a suggested focused test selection for document management, not a recorded passing result. Run the test command in the intended local environment before reporting it as passed.

Frontend checks:

```powershell
cd E:\SaviraCortex\frontend
npm run lint
npm run build
```

## 31.13 Verification status and known limitations

No test suite was run as part of this documentation-only update. Earlier test results in [21 — Testing](21-testing.md) are historical and scoped to their exact commands.

The inspected development workspace contains uncommitted changes in both repositories:
- Backend: ingestion workflow/API, router, Qdrant, B2 storage, tests, and untracked document-management endpoint/schema/service/tests.
- Frontend: batch-ingestion widget, dashboard and untracked document-library component.

These changes are not represented as committed, pushed or deployed by this document. Documentation is being updated against the working tree, including those changes. Review the Git diff before committing.

Known boundaries to keep visible:
- Persistent conversation records/history management are not established by the current generation request's conversation-history field.
- Durable ingestion job orchestration is not established by a browser progress widget.
- Production deployment, monitoring, rate limiting, backup/restore and full security review are separate operational concerns.
- Tenant-isolation and retrieval regression tests must be kept current; earlier smoke tests are not proof of a security pass.
- A feature being present in source is not proof that external services, browser flows or production credentials are correctly configured.

## 31.14 Documentation maintenance

When a feature changes:
1. Update the relevant subsystem page.
2. Update this current-state checkpoint if product behavior, API surface, architecture or verification changes.
3. Update the root README only if onboarding or navigation changes.
4. Record exact test commands/results and environment.
5. Separate implemented behavior from planned work.
6. Never include secrets or real user document contents.
