# 1. Project Overview

**Product:** SaviraCortex  
**Documentation checkpoint:** 7 November 2026

## 1.1 Purpose

SaviraCortex is an organization-aware document intelligence and retrieval-augmented generation (RAG) platform. Organizations manage members, roles and departments; ingest and version PDF documents; apply document-level access controls; and ask questions answered from authorized indexed evidence.

The product is a full-stack application:
- FastAPI backend with a versioned `/api/v1` API.
- Next.js App Router frontend.
- Firebase Authentication for external identity.
- PostgreSQL/SQLAlchemy for application and tenant records.
- Backblaze B2 for original document objects.
- Qdrant for document chunk and summary vectors.
- Redis-compatible cache infrastructure.
- LLM, embedding and OCR components for processing and generation.
- LangGraph orchestration and deterministic answer/citation validation.

## 1.2 Capabilities represented in the current source

### Organization administration
- Firebase Email/Password, Google and Phone authentication.
- SaviraCortex user identity linked to verified Firebase UID.
- Organization creation, listing and updates.
- Organization memberships and role updates.
- Custom organization roles and role assignments.
- Department creation and department membership assignment.
- Invitation creation, preview, acceptance and listing.

### Document intelligence
- PDF validation, native text extraction and OCR fallback.
- Text normalization, page-aware extraction and hashing.
- Document summarization and duplicate detection.
- Logical document registration and version lifecycle.
- Original PDF storage in Backblaze B2.
- Chunking, embeddings and Qdrant chunk/summary indexing.
- Pending-version indexing retry.
- Document library, metadata and summary editing, archive/restore, superseding versions and permanent deletion.

### RAG and generation
- Organization/member-aware evidence retrieval.
- Dense and lexical/hybrid candidate retrieval, fusion, reranking and adaptive selection.
- Evidence sufficiency evaluation and bounded retrieval expansion.
- Conditional context compression.
- Structured answer generation.
- Static output/citation validation.
- Non-streaming and Server-Sent Events generation endpoints.

### Frontend
- Public homepage, login and registration.
- Invitation acceptance.
- Organization dashboard with roles, members, departments and invitations.
- Document ingestion modal and batch progress widget.
- Document library and version detail workflows.
- Organization chat page.

### Evaluation
- Dataset synthesis modules and generated golden datasets.
- Ingestion and answer evaluation entry points.
- Stored evaluation result artifacts.

## 1.3 Primary workflows

### Authentication and organization access
1. Browser authenticates through Firebase and obtains an ID token.
2. Frontend sends the token as a Bearer token.
3. FastAPI verifies it with Firebase Admin.
4. Backend resolves the Firebase UID to a SaviraCortex user.
5. Services verify organization membership and required role before organization operations.

### Document ingestion
1. Analyze/stage or stream-upload a PDF.
2. Validate, extract, normalize, hash, summarize and detect duplicates.
3. Confirm metadata and register a logical document/version.
4. Store the source file in B2.
5. Chunk, embed and index the content and summary in Qdrant.
6. Activate the version only after indexing succeeds; preserve pending state for retry on failure.

### Document management
Authorized organization administrators can list and inspect documents, edit metadata and version summaries, archive/restore, upload a superseding version, and permanently delete a document. Deletion spans PostgreSQL, B2 and Qdrant; it must remain retryable if an external cleanup step fails.

### RAG generation
1. Verify the caller's Firebase identity and organization membership.
2. Validate the query and retrieve authorized evidence.
3. Evaluate evidence sufficiency and perform bounded expansion if required.
4. Compress context when the workflow threshold is met.
5. Generate a structured answer and validate citations.
6. Return the answer directly or stream SSE events.

## 1.4 System boundaries

- **Firebase:** identity provider; not the application membership/role database.
- **FastAPI:** token verification and application authorization enforcement.
- **PostgreSQL:** authoritative relational and tenant records.
- **Qdrant:** search vectors/payloads; similarity is not authorization.
- **Backblaze B2:** original document objects.
- **Next.js:** user interface; UI visibility is not an authorization boundary.
- **Evaluation resources:** must be isolated from ordinary application data.

## 1.5 Current-state and verification references

See [31 — Project-Wide Current State](31-project-wide-current-state.md) for current APIs, architecture, model inventory, local commands and known limitations.

No tests were run as part of the 7 November 2026 documentation refresh. Historical test evidence is in [21 — Testing](21-testing.md). Source presence is not proof of integration or production readiness.
