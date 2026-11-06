# 28. Remaining Implementation Roadmap

**Status date:** 5 November 2026  
**Scope:** Remaining application coding work after the Generation Agent and Static Validation Layer were implemented and their focused tests passed.

This page is an implementation roadmap, not a claim that the listed future components already exist. Existing source code remains authoritative. The roadmap separates completed components, the next integration milestone, and later application work so that the next phase does not duplicate existing functionality.

## 28.1 Current implementation baseline

The following work is present in the repository:

| Component | Current implementation | Verification |
|---|---|---|
| Retrieval algorithms | Dense, BM25/hybrid retrieval, fusion, reranking and adaptive-K components under `app/rag/retrieval/` | Existing component tests; see retrieval test modules |
| Retrieval orchestration | `RetrievalOrchestrator` in `app/services/retrieval/retrieval_service.py` coordinates authorization-scoped retrieval, multi-query generation, candidate-document generation, retrieval branches, fusion, reranking and adaptive selection | Existing retrieval integration test module |
| Generation Agent | `app/agents/Generation/` with structured company-grounded output | 11 focused tests passed |
| Generation streaming | `GenerationAgent.astream_generate()` emits provisional content deltas and a completed event containing the parsed output after its citation-ID check | Covered by Generation Agent tests |
| Static Validation Layer | `app/validation/` parses output, validates request-scoped citation IDs, enforces basic status/citation consistency, and maps cited IDs to allowlisted document metadata | 6 focused tests passed |

### Focused verification recorded on 4 November 2026

The user ran:

```powershell
uv run pytest tests/agent/test_generation.py tests/agent/test_generation_validation.py -v
```

Reported result: **17 passed in 6.14 seconds** (11 Generation Agent tests and 6 Static Validation tests). This verifies those two focused test modules only. It is not a full-suite or production integration test.

## 28.2 Important distinction: retrieval orchestration versus end-to-end LangGraph orchestration

There are two different orchestration responsibilities:

1. **Existing retrieval orchestration:** `RetrievalOrchestrator` is already implemented in `app/services/retrieval/retrieval_service.py`. Its public operation is asynchronous `retrieve(...)`. It returns a dictionary containing `selected_candidates` and retrieval diagnostics such as counts, generated queries, branches and expansion details.
2. **Completed end-to-end orchestration:** The LangGraph RAG workflow now coordinates the existing retrieval orchestrator, evidence evaluation, bounded retrieval expansion, optional context compression, Generation Agent and Static Validation Layer to produce a validated workflow result.

The Multi-Query Generator already uses a one-node LangGraph, but that is not the end-to-end RAG graph.

**Implementation rule:** The new graph must call the existing retrieval orchestrator. It must not reimplement authorization, multi-query generation, candidate selection, retrieval branches, fusion, reranking or adaptive-K behavior.

## 28.3 Completed milestone: end-to-end LangGraph orchestration

This milestone was completed on 5 November 2026. The design checklist below records the component contracts and implementation requirements that were used; the current verified implementation status is summarized in section 28.10.

### A. Inspect and freeze component contracts

Before implementation, confirm the actual public interfaces and agree on the graph's input/output contract.

Required inputs will need to account for:

- Current user query.
- Organization and user identifiers required by retrieval authorization.
- Optional chronological LangChain conversation history.
- Retrieval configuration such as `top_k`, `candidate_k`, `mode` and `rrf_k`, using the existing retrieval defaults unless the application contract specifies otherwise.

The graph's public response should preserve the structured Generation output and the Static Validation result. Decide explicitly which retrieval diagnostics are returned to the caller and which remain internal.

### B. Define graph state

Design a typed state that carries only the data needed between nodes. Candidate fields to evaluate include:

- Request inputs: query, organization ID, user ID and optional conversation history.
- Retrieval result, including the original ordered `selected_candidates` list.
- Generation output.
- Static validation result.
- A structured failure/error field or equivalent graph error handling.
- Any approved retrieval diagnostics needed in the final response.

Finalize field names and required/optional semantics from the actual component contracts before coding. Do not copy the entire retrieval result into the LLM prompt.

### C. Define graph nodes and flow

The expected logical stages are:

1. **Retrieve:** asynchronously call the existing `RetrievalOrchestrator.retrieve()`.
2. **Generate:** call `GenerationAgent.agenerate()` with the current query, optional history and the exact `selected_candidates` list.
3. **Validate:** call `static_validation_layer.validate_generation_output()` with the Generation output and that same original ordered candidate list.
4. **Return:** produce the agreed final response only after deterministic validation has completed.

The graph should coordinate these components rather than copy their internal logic.

### D. Preserve evidence identity

This is a critical integration invariant:

- Generation assigns `E1`, `E2`, ... using the order of usable retrieval candidates.
- Static Validation reconstructs the same evidence registry from the original ordered candidates, skipping blank/non-string chunk content in the same way.
- The graph must pass the same candidate list, without sorting, filtering, rebuilding or otherwise changing its order, to both components.
- Do not treat request-scoped evidence IDs as canonical document IDs.

### E. Define empty-result and failure behavior

Design and test these cases explicitly:

- No authorized document versions / empty retrieval result.
- Retrieval returns no selected candidates.
- Candidate generation reports its handled failure result.
- Retrieval raises an unexpected exception.
- Generation returns the deterministic insufficient-evidence output when no usable evidence remains.
- Generation or parsing fails.
- Static Validation returns an invalid result.
- Static Validation returns warnings while the result remains valid.

Do not silently convert unexpected failures into a successful insufficient-evidence answer. Preserve the distinction between a legitimate no-evidence result and an operational failure.

### F. Add graph integration tests

Use injected or mocked component dependencies so graph tests do not require live model calls or production services.

At minimum, cover:

- Successful retrieval → generation → validation.
- Conversation history reaches Generation unchanged.
- The exact ordered `selected_candidates` object/list is passed to Generation and Validation.
- Empty retrieval reaches the deterministic insufficient-evidence path.
- Invalid citation IDs or invalid validation results do not produce a successful final response.
- Retrieval and generation failures remain distinguishable.
- Validation warnings are preserved without being incorrectly treated as hard failures.
- Final response schema and graph state behavior.

The graph should be tested independently before connecting it to an HTTP API.

## 28.4 Streaming orchestration

Generation streaming exists, but end-to-end graph streaming is not implemented.

After the non-streaming graph contract is stable:

1. Decide how graph-level streaming events are represented.
2. Forward Generation content deltas as provisional output.
3. Preserve `segment_index` so the consumer can reconstruct segment boundaries.
4. Do not emit a final successful/completed response until the complete output has passed Static Validation.
5. Define the terminal error event/behavior if validation fails after provisional text has already been emitted.
6. Test empty-evidence streaming and stream failures.

A Generation `COMPLETED` event means its own parsing and citation-ID check succeeded. The end-to-end workflow must still run the broader Static Validation operation before declaring the whole request successful.

## 28.5 Citation resolution and protected document access

Static Validation currently maps evidence IDs to allowlisted metadata. It deliberately does not generate URLs or make documents accessible.

Future backend work:

1. Inspect the existing document repository, version model, storage abstraction and authorization-service contracts.
2. Design a citation resolver that accepts validated citation references and resolves trusted document/version identifiers to an application-owned document-viewer reference.
3. Ensure the resolver does not trust LLM-generated URLs, storage paths or permission claims.
4. Check the current user and document-level authorization on every document open.
5. Define consistent not-found and access-denied behavior.
6. Support page navigation where the stored document format and viewer permit it.

Do not implement a resolver by guessing storage keys or inventing document routes. Base it on the real repository, storage and permission contracts.

## 28.6 FastAPI application and API routes

The reviewed application currently has no implemented FastAPI entry point or endpoint modules:

- `app/main.py` is a placeholder.
- `app/api/v1/endpoints/` is empty.

Future API work, after the graph contract is stable:

1. Establish the FastAPI application entry point and router registration.
2. Define request/response Pydantic schemas for the chat workflow.
3. Add authenticated request dependencies and pass trusted organization/user identity into retrieval.
4. Add the chat endpoint that invokes the end-to-end graph.
5. Add protected citation/document-viewing routes after the citation resolver and authorization behavior are defined.
6. Add API tests for authentication, authorization, validation failures and response serialization.

The API layer should call the graph; it should not reimplement graph nodes or retrieval/generation logic.

## 28.7 Frontend citation interaction

Frontend implementation is not present in the reviewed API/application tree and remains future work.

The intended division of responsibility is:

- Generation returns answer segments with evidence IDs.
- Static Validation returns trusted metadata for cited evidence IDs.
- The API/citation resolver exposes an authorized application-level document reference.
- The frontend renders citation markers as clickable controls and opens the document viewer.
- The viewer navigates to a cited page when supported.

A citation marker is not itself an authorization grant. The backend must authorize every document request.

## 28.8 Evaluation and broader verification

Keep retrieval evaluation separate from end-to-end RAG evaluation.

### Layer 1 — retrieval evaluation

The existing `docs/Layer 1 evaluation.md` describes the retrieval benchmark and metric plan. Its remaining work includes generating/reviewing the benchmark candidates, approving ground-truth relevance labels, implementing/validating the evaluator, running the planned retrieval experiments and reporting results. The Generation Agent does not replace this work.

### Layer 2 — end-to-end RAG evaluation

After the end-to-end graph exists, extend evaluation to cover:

- Query and retrieved contexts.
- Generated answer and expected/reference answer where available.
- Faithfulness / groundedness.
- Answer relevance and correctness.
- Citation behavior and failure cases.
- End-to-end latency and component-level timing.

Use the pinned library APIs and the actual evaluation objective. Do not introduce a second LLM citation-verification call by default; semantic verification strategy remains a separate product/architecture decision.

### Regression and runtime verification

After integration, run the focused tests, relevant retrieval/service tests, graph integration tests and then the full test suite in the appropriate test environment. Tests requiring PostgreSQL, Redis/Valkey, Qdrant or model credentials must use isolated test resources.

## 28.9 Updated implementation sequence (5 November 2026)

| Order | Work item | Completion condition |
|---:|---|---|
| 1 | Complete Layer 1 retrieval evaluation | Existing corpus, datasets, judgments and scripts audited; metrics validated; reproducible experiment report reviewed |
| 2 | Establish FastAPI application and authenticated chat API | Graph composition, request/response schemas, authentication and API tests are complete |
| 3 | Implement trusted citation resolution and protected document viewing | Document/version resolution uses real repository and authorization contracts; every open is authorized |
| 4 | Implement frontend chat and citation interaction | Chat consumes the API; citations open only authorized documents in the viewer |
| 5 | Add frontend document viewer and page navigation | Viewer handles loading, denied access, missing documents and supported page navigation |
| 6 | Add Layer 2 end-to-end RAG evaluation | Answer quality, faithfulness, citation behavior and end-to-end latency are evaluated after API contracts stabilize |
| 7 | Run broader regression and operational checks | Focused, workflow, full-suite and isolated integration checks pass |
| 8 | Add graph-level streaming when the non-streaming API/UI contract is stable | Provisional deltas are never represented as a validated final response |
| 9 | Complete deployment, observability and operational hardening | Readiness checks, logging, metrics, secrets and failure handling are reviewed |
| 10 | Maintain regression evaluation | Retrieval and answer-quality benchmarks run on approved changes |

## 28.10 Current status summary

**Completed and locally verified:**
- End-to-end LangGraph RAG workflow, including input validation, retrieval, evidence evaluation, bounded expansion, conditional context compression, Generation, and Static Validation.
- 45 workflow tests passed; 393 full-suite tests passed with 2 warnings.
- Generation Agent implementation.
- Generation synchronous, asynchronous and streaming interfaces.
- Request-scoped citation-ID existence checks.
- Static Validation Layer and citation metadata mapping.
- 17 focused Generation and Validation tests.

**Existing and reusable:**
- Retrieval algorithms and retrieval service.
- Retrieval-only `RetrievalOrchestrator`.
- Multi-Query Generator's one-node LangGraph.
- Authorization, repository and storage components that must be inspected before citation/document API implementation.

**Next implementation milestone:**
- Layer 1 retrieval evaluation using the existing frozen corpus, question datasets, relevance judgments, metrics, and runner scripts.

**Not yet implemented as part of this end-to-end workflow:**
- Graph-level streaming.
- Citation resolver and protected document-viewer API.
- FastAPI application/routes.
- Frontend clickable citation/document viewer integration.
- Completed Layer 1 benchmark/evaluation run and Layer 2 end-to-end RAG evaluation.

This status is scoped to the reviewed source and the focused test output recorded above. It does not claim that the full repository test suite or production deployment has been verified.

---

## 28.11 Authoritative status update — 5 November 2026

This section supersedes earlier roadmap statements that described the end-to-end LangGraph RAG workflow as not yet implemented.

### Completed

- End-to-end LangGraph graph in `app/workflows/rag/graph.py`, with typed workflow state, conditional routing, injected node dependencies, and a three-total-attempt retrieval limit.
- Reuse of the existing RetrievalOrchestrator for initial and subsequent retrieval attempts.
- Backward-compatible chunk exclusion across dense and BM25 retrieval branches.
- Input validation, Retriever, Evidence Sufficiency Evaluator, Retrieval Expansion, Context Compression, Generation, and Static Validation workflow nodes.
- Context compression activation based only on accumulated unique retrieved-document count greater than 15.
- Workflow tests: 45 passed in 29.84 seconds.
- Full repository suite: 393 passed with 2 warnings in 163.43 seconds.
- Local E2E smoke-test runner and a synthetic indexed policy PDF fixture.

### Current findings and limits

- The local E2E run using the ingestion-created organization/user identity successfully retrieved evidence and generated grounded answers for the first two scenarios.
- A later run under a different tenant identity showed inconsistent evidence availability across the three scenarios. Tenant isolation and retrieval scoping require a focused investigation; neither a security pass nor a confirmed leak should be claimed yet.
- The E2E script's current pass count reflects workflow completion and static validation, not semantic correctness or full-answer coverage.
- No FastAPI chat/document API, citation resolver, protected document-viewer route, or frontend chat/citation viewer has been implemented as part of this workflow.

### Updated next sequence

1. Audit and complete Layer 1 retrieval evaluation using the existing frozen corpus, generated questions, relevance judgments, metrics, and scripts. Validate benchmark quality before reporting scores.
2. Implement the backend: FastAPI application and authenticated chat API, composition of the existing graph, trusted citation resolution, and protected document viewing.
3. Implement the frontend: chat interface, clickable evidence citations, and an authorized document viewer with page navigation where supported.
4. Add Layer 2 answer-quality/faithfulness evaluation after the end-to-end API contract is stable.
5. Investigate tenant-scoped retrieval behavior before treating the E2E setup as a security validation.

Do not duplicate the existing retrieval or graph components when building the API. The backend should compose and invoke the current graph, and every document open must perform authorization.

---

## 28.12 Application/API checkpoint update — 5 November 2026

This section supersedes the earlier statements in sections 28.6 and 28.7 that FastAPI routes and the frontend application were absent. Those statements describe the earlier RAG-only checkpoint and are no longer the current repository state.

### Implemented since the previous checkpoint

- FastAPI application at `app/main.py`, with CORS configuration and versioned router.
- API documentation endpoints at `/api/v1/docs`, `/api/v1/redoc` and `/api/v1/openapi.json`.
- Firebase Admin ID-token verification dependency.
- Authentication routes: `GET /api/v1/auth/me` and `POST /api/v1/auth/organizations/signup`.
- Organization signup and identity/profile services.
- Department request/response schemas, repository, service and API routes.
- Department list access for organization members and create access for organization owners/admins.
- Next.js homepage, Firebase login and registration flows, organization dashboard and department create/list UI.
- Focused auth/department schema and auth service tests: user-reported **20 passed in 2.33 seconds** on 5 November 2026.

### Current implementation boundary

The department feature reuses the existing organization-department model/table and organization/name uniqueness. The latest test command did not run dedicated department service authorization tests, API integration tests or a live database persistence test. Frontend build/lint/browser verification is also not recorded.

### Updated next work

1. Add department service tests for membership, roles, duplicate names and transaction rollback.
2. Add authenticated API integration tests using an isolated database.
3. Verify the actual PostgreSQL department schema and unique constraint.
4. Run frontend lint/build and browser verification for the complete registration-to-dashboard flow.
5. Continue the previously identified retrieval tenant-scope investigation and Layer 1 evaluation.
6. Implement chat API/UI and protected citation/document viewing as separate milestones.

See [30 — Current Application Checkpoint](30-current-application-checkpoint.md) for the full chronology, file map, test evidence and resumption instructions.
