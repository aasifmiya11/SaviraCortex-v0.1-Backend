# 1. Project Overview

**Product:** SaviraCortex  
**Repository:** `E:\\SaviraCortex`  
**Documentation checkpoint:** 5 November 2026

## 1.1 Purpose

SaviraCortex is an organization-centric knowledge and AI platform. Its backend processes organizational documents, indexes their contents, retrieves evidence under organization-scoped authorization, and coordinates a retrieval-augmented generation (RAG) workflow. Its Next.js frontend provides public entry, authentication, registration, and an organization dashboard.

The backend is a modular Python application exposed through a versioned FastAPI API. Firebase Authentication manages user identity; PostgreSQL stores SaviraCortex users, organizations and memberships. The document intelligence pipeline additionally uses Qdrant for vector retrieval and Backblaze B2 through an S3-compatible storage abstraction for original files.

## 1.2 Capabilities represented in the repository

### Document intelligence
- Validate PDF inputs, extract native text and use OCR where required.
- Normalize extracted text, preserve page information and calculate hashes.
- Summarize documents and compare incoming documents with existing records.
- Register logical documents and document versions.
- Store original PDFs in object storage.
- Split content into chunks, generate embeddings and index chunks and document summaries in Qdrant.
- Retrieve authorized evidence using dense and lexical/hybrid retrieval, fusion, reranking and adaptive selection.

### RAG workflow
- Coordinate input validation, retrieval, evidence sufficiency evaluation and bounded retrieval expansion.
- Optionally compress accumulated evidence when the workflow's unique-document threshold is exceeded.
- Generate structured, organization-grounded answers.
- Run deterministic static validation over generated output and request-scoped citation identifiers.

### Identity and organization setup
- Firebase Email/Password, Google and Phone identity providers are supported by the frontend authentication flow.
- The backend verifies Firebase ID tokens and maps the Firebase UID to a SaviraCortex user.
- Organization signup creates the initial organization and its owner/admin membership.
- Authenticated users can retrieve their profile and organization memberships.
- Organization owners and admins can create departments; organization members can list departments.

### Frontend
- Public homepage with responsive sections and CSS-driven motion.
- Login and registration flows.
- Organization dashboard with organization-specific department listing and creation form.

## 1.3 Primary workflows

### Registration and authentication
1. The user authenticates through Firebase using Email/Password, Google or Phone.
2. Email registration requires email verification before organization signup.
3. The frontend obtains a Firebase ID token and sends it as a Bearer token.
4. FastAPI verifies the token through Firebase Admin.
5. Organization signup creates the SaviraCortex user, organization and initial membership.
6. The authenticated profile endpoint returns the user and organization memberships.

### Department management
1. The dashboard loads the authenticated profile and its organization memberships.
2. For each organization, it requests that organization's departments.
3. The backend verifies the Firebase identity and confirms organization membership.
4. Owners/admins may create a department. Other members may list but cannot create.
5. PostgreSQL enforces organization-scoped department-name uniqueness.

### Document ingestion and indexing
A PDF is validated, extracted, normalized, hashed, summarized and checked for duplicates. A new document/version is uploaded and registered as pending. Indexing chunks and embeds the content, writes vector records and activates the version in the relational database.

### Retrieval and answer generation
The RAG workflow calls the existing RetrievalOrchestrator, evaluates evidence sufficiency, performs bounded expansion where required, conditionally compresses accumulated context, generates an answer and validates the output/citations.

## 1.4 Main system boundaries

- **Firebase Authentication:** external identity provider; credentials are not stored by the SaviraCortex application.
- **FastAPI:** verifies Firebase tokens and enforces SaviraCortex membership/role checks for API operations.
- **PostgreSQL:** authoritative relational identity, organization, membership, department, document and lifecycle data.
- **Qdrant:** vector data and retrieval payloads; vector similarity is not an authorization grant.
- **Backblaze B2:** original document objects through S3-compatible storage.
- **Next.js:** browser UI; authorization decisions remain backend responsibilities.

## 1.5 Verification boundaries

The 5 November 2026 department/auth checkpoint includes a user-reported local result of 20 passing focused backend tests. This verifies the department request schema, auth request schema and auth service tests. It does not yet verify department service authorization branches, real database persistence, endpoint integration, frontend type-check/build, or production deployment.

See [Testing](21-testing.md), [Authorization](07-authorization.md), and [Current application checkpoint](30-current-application-checkpoint.md).
