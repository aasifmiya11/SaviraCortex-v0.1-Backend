# SaviraCortex Generation Pipeline — Architecture Memory

Workspace: `E:/Voice-AI`
File: `.ChatGPT/Generation Memory.md`
Created: 2026-11-04

## 1. Purpose of this memory

This file preserves the discussion, architectural direction, constraints, and open decisions for the SaviraCortex **generation pipeline**. It is intended to be read by future agents or contributors before they design or implement this subsystem.

This is a working architecture memory, not a claim that the design has already been implemented. Where an idea was proposed but not explicitly finalized, it is marked as a proposal or an open decision.

## 2. Current project direction

The user wants to build the generation pipeline as an independent subsystem first.

The intended high-level sequence is:

1. Build and understand the generation block independently.
2. Define its architecture, contracts, inputs, outputs, and behavior.
3. Implement and test that block independently of the end-to-end orchestrator.
4. Only later build the AI orchestrator that coordinates the complete workflow.

The generation pipeline is expected to receive:
- the current user query;
- relevant conversation/context supplied by its caller;
- retrieved documents/evidence supplied by the retrieval layer.

It is responsible for turning those inputs into a grounded, structured answer.

### Explicit boundaries

- **Do not build the AI orchestrator as part of the initial generation-pipeline task.**
- **Do not make generation call retrieval internally.** Retrieval is upstream and supplies evidence to generation.
- **Do not make a FastAPI endpoint the initial focus.** The user wants the generation architecture and behavior defined and built as an independent block first.
- Keep the pipeline independently testable and reusable so that a later orchestrator can call it.
- The evaluation-documentation task is assigned to another agent. It is outside the scope of this generation-memory task.
- The user previously restricted the current work to documentation / `.ChatGPT` scope and explicitly said not to change application code for the documentation-only work. Do not infer permission to modify production code from this memory; get explicit authorization when implementation is requested.

## 3. Architectural principle

Treat generation as a **bounded, contract-driven application component**, not as an all-in-one agent that decides how the entire system operates.

The caller owns orchestration and provides the inputs. Generation owns:
- input validation and normalization;
- preparing the supplied context and evidence for the model;
- prompt selection and construction;
- invoking the configured language model;
- parsing and validating the model output;
- validating evidence/citation references against the supplied evidence;
- returning a stable structured response.

Generation does not own:
- document ingestion or indexing;
- retrieval, query expansion, hybrid search, fusion, reranking, or adaptive-K selection;
- authorization decisions or fetching arbitrary private documents;
- end-to-end workflow orchestration;
- frontend rendering or React component generation;
- deciding its own upstream context by reaching into unrelated services.

A later AI orchestrator can coordinate query understanding, retrieval, generation, and any other tools or stages. It should call generation through a stable interface rather than embedding generation logic into the orchestrator.

## 4. Proposed internal pipeline

The following staged flow was proposed for the independent generation block:

```text
GenerationRequest
      |
      v
1. Input validation and normalization
      |
      v
2. Context and evidence preparation
      |
      v
3. Prompt construction / prompt selection
      |
      v
4. LLM generation
      |
      v
5. Output parsing and structural validation
      |
      v
6. Grounding and citation validation
      |
      v
7. Structured GenerationResponse
```

### Stage 1 — Input validation and normalization

Validate the request before spending an LLM call:
- query is present and usable;
- conversation context has supported roles and valid message content;
- evidence collection is structurally valid;
- evidence identifiers are unique within the request;
- required source metadata is present where the contract requires it;
- configured generation options are within allowed bounds.

Normalize only safe, well-defined fields. Do not silently rewrite the user's intent or invent missing evidence metadata.

### Stage 2 — Context and evidence preparation

Prepare the inputs for the prompt:
- distinguish the current query from prior conversation history;
- preserve the order of conversation messages;
- keep retrieved evidence separate from conversation text;
- assign or preserve stable evidence identifiers;
- retain source metadata needed later for citations;
- handle context-window limits deliberately.

If evidence must be shortened or selected to fit a model context window, make that operation explicit and traceable. Do not silently discard provenance or claim the model saw evidence that was not actually supplied.

The generation component should not fetch more evidence from Qdrant or another retrieval service. If evidence is insufficient, it should return a meaningful status or limitation rather than secretly performing retrieval.

### Stage 3 — Prompt construction

Keep prompt construction separate from the LLM client and from output validation.

Recommended direction:
- use reusable, versioned prompt templates;
- define system instructions and task-specific instructions explicitly;
- clearly label user query, conversation history, and evidence;
- instruct the model to ground factual claims in supplied evidence;
- instruct the model to cite only supplied evidence identifiers;
- instruct the model not to fabricate document names, page numbers, IDs, or URLs;
- define behavior for insufficient, conflicting, or irrelevant evidence.

Prompt version / identifier should be available in execution metadata for debugging and evaluation.

### Stage 4 — LLM generation

Use a provider/client abstraction so the pipeline is not tightly coupled to one model vendor.

The generation service should receive a configured model client and generation configuration rather than constructing unrelated provider clients throughout the pipeline.

Keep provider-specific details behind the client boundary where practical:
- model identifier;
- temperature and token limits;
- timeout / retry behavior;
- structured-output or tool/function-calling mode;
- token usage and provider response metadata.

Retries should be bounded and should distinguish transient provider failures from invalid model output. Avoid retrying indefinitely.

### Stage 5 — Output parsing and structural validation

Treat model output as untrusted until parsed and validated.

Use typed contracts (Pydantic was proposed, consistent with the Python project) to validate:
- response shape;
- allowed content-block types;
- citation identifier types;
- required fields;
- supported status values;
- basic content constraints.

Malformed output should produce a typed failure or a controlled repair/retry path. Never pass malformed model output directly to the frontend as if it were a valid response.

### Stage 6 — Grounding and citation validation

The model must only refer to evidence that was actually supplied in the generation request.

The backend should:
- validate every returned evidence/citation ID against the request's evidence set;
- reject or remove unknown identifiers according to an explicit policy;
- ensure source metadata is resolved from trusted backend data, not invented by the model;
- preserve the association between answer content and supporting evidence;
- represent unsupported / insufficiently supported answers honestly.

The model may select evidence IDs and produce answer content. It must not be trusted to author canonical document identity, authorization decisions, storage keys, or private download URLs.

### Stage 7 — Structured response

Return a stable, typed response object. Do not return only an unstructured string if the product needs citations, document references, progressive rendering, or other structured UI.

The exact schema should be versioned and treated as a backend/frontend contract.

## 5. Input contract — conceptual shape

The following is a conceptual contract, not a finalized Python schema:

```json
{
  "request_id": "stable-request-id",
  "query": "The current user question",
  "conversation_context": [
    { "role": "user", "content": "Earlier user message" },
    { "role": "assistant", "content": "Earlier assistant response" }
  ],
  "evidence": [
    {
      "evidence_id": "ev-001",
      "text": "The supplied retrieved chunk text",
      "document_id": "trusted-document-id",
      "document_version_id": "trusted-version-id",
      "chunk_id": "trusted-chunk-id",
      "source": "source-filename.pdf",
      "page": 4,
      "chunk_index": 12,
      "start_index": 850
    }
  ],
  "options": {
    "response_style": "default"
  }
}
```

Contract notes:
- `query` is the current turn, not a replacement for conversation history.
- `conversation_context` contains prior turns only, in chronological order.
- `evidence` is supplied by the caller after retrieval and any upstream authorization filtering.
- `evidence_id` is a request-scoped stable handle that the model can safely return.
- Source identifiers and metadata are backend-trusted values.
- Options should be explicit and bounded. Do not allow arbitrary model/provider parameters to leak into public request contracts.

The exact field names and optionality remain to be finalized against the codebase and frontend requirements.

## 6. Output contract — conceptual design

The discussion established an important distinction: the backend should define the response schema, and the frontend should render that schema. The LLM should not generate React, HTML, or frontend implementation code.

A useful conceptual separation is:

1. **GenerationResponse** — the complete logical answer.
2. **ContentBlock** — typed units that make up the answer.
3. **Citation** — association between answer content and known evidence.
4. **SourceReference** — trusted document/source information resolved by backend.
5. **StreamingEvent** — transport events emitted while the response is being generated.

### 6.1 GenerationResponse

Conceptual fields:
- `response_id`;
- `schema_version`;
- `status` (for example: completed, insufficient_evidence, failed);
- `blocks` — ordered content blocks;
- `citations` — validated citation associations;
- `sources` — unique source references used by citations;
- `metadata` — safe operational metadata such as model/prompt version and usage, where appropriate.

### 6.2 ContentBlock

Content should be represented as typed blocks instead of forcing every response into one long string.

Potential block types discussed:
- `text`;
- `heading`;
- `list`;
- `table`;
- `document_reference`.

Each block can carry:
- a stable `block_id`;
- its `type`;
- its content / type-specific payload;
- citation IDs associated with that block.

The set of block types should remain intentionally small at first. Add new types only when there is a clear product requirement and a defined frontend renderer.

A block schema is not a license for the model to output arbitrary UI. The backend validates the block type and payload, and the frontend maps supported types to its own components.

### 6.3 Citation

A citation should map a citation identifier to one or more evidence identifiers / source identifiers.

Conceptual example:

```json
{
  "citation_id": "cite-001",
  "evidence_ids": ["ev-001", "ev-003"]
}
```

A content block can refer to `cite-001`. The frontend can then render an inline citation marker and connect it to the corresponding source details.

Citation semantics and whether citations attach at block, sentence, or finer granularity remain to be finalized. Start with block-level association unless the UX requires more precise attribution.

### 6.4 SourceReference

Source references should be resolved by the backend from trusted document metadata. They should contain only information the caller is authorized to receive.

Potential fields:
- `source_id`;
- `document_id`;
- `document_version_id`;
- `title`;
- `source_filename`;
- `version_number`;
- `page` and/or chunk location;
- `document_link` (a backend-resolved, authorized link, if available).

The model should never invent a source URL or download link.

## 7. Document links, provenance, and authorization

The existing codebase inspection established these relevant facts:

- Indexing metadata includes `organization_id`, `document_id`, `document_version_id`, `version_number`, `source`, `chunk_index`, and indexing status.
- PDF page metadata can include `source`, `page`, `native_text_length`, `ocr_attempted`, `ocr_used`, and `extraction_method`.
- The recursive splitter uses `add_start_index=True`, so chunk start positions may be available.
- Retrieval returns chunk text and metadata with rank/score information.
- Global fusion enriches candidates with values such as `global_rank`, `global_rrf_score`, `chunk_id`, and `provenance`.
- Cross-encoder reranking adds `reranker_score`.
- Adaptive-K selection produces the final selected candidates.
- PostgreSQL document catalogue models hold document/version identity and fields such as title, summary, version year/status, and last-updated details.
- Private B2 storage is used. The inspected storage layer has `FileStorage.generate_download_url(storage_key, expiration_seconds=900)`.
- Retrieval was not observed returning a user-facing document URL, and chunk metadata was not observed carrying the storage key.
- Existing authorization service/repository code is relevant to determining whether a user can access a source.

Consequences for generation:
1. Carry evidence provenance through generation without losing chunk/document/version IDs.
2. Join source details using trusted backend identifiers, not model-generated values.
3. Resolve a private document link only after the relevant authorization check.
4. Use the correct document/version storage key internally; never expose storage keys.
5. Treat generated or signed URLs as backend-owned data, not LLM output.
6. If an authorized link cannot be resolved, return source metadata without a link rather than inventing one.
7. Do not assume that a retrieved chunk's existence alone grants the current user permission to open its parent document.

These are integration requirements inferred from the inspected codebase. The exact service/module responsible for source resolution still needs to be chosen during implementation.

## 8. Streaming and progressive response delivery

The user asked about producing a complete response versus showing it progressively as an instructor-like output. The architectural direction discussed was to distinguish the logical response schema from the way that response is delivered to the UI.

A structured response can be streamed as a sequence of typed events. The frontend can progressively render content while preserving a final response contract.

Potential event types:
- `response_started`;
- `block_started`;
- `block_delta`;
- `block_completed`;
- `citation_added`;
- `source_added`;
- `response_completed`;
- `response_error`.

Conceptual event envelope:

```json
{
  "event_id": "evt-001",
  "response_id": "resp-001",
  "sequence": 1,
  "type": "response_started",
  "timestamp": "ISO-8601 timestamp",
  "data": {}
}
```

Streaming design principles:
- Every event belongs to one response and has a monotonic sequence number.
- Event payloads are typed and validated.
- The frontend should not need to infer event meaning from arbitrary text.
- Content blocks can be emitted progressively, then explicitly completed.
- Citations should be surfaced only after their IDs have been validated against supplied evidence.
- Source details and links should be emitted only after trusted backend resolution and authorization.
- The final completed response should be reconstructable from the event stream.
- Errors and cancellation should have explicit semantics.
- Do not confuse a partial streamed block with a finalized, citation-validated block.

Server-Sent Events (SSE) was suggested as a reasonable initial server-to-client transport if/when an API endpoint is introduced. This is a proposal, not a finalized transport decision. The user explicitly does not want the endpoint/orchestrator to be the first implementation focus.

## 9. Frontend/backend responsibility split

The agreed direction is **backend-defined contract, frontend-owned rendering**.

Backend responsibilities:
- define and version request/response/event schemas;
- validate model output;
- validate citation/evidence IDs;
- resolve document/source metadata;
- enforce authorization before returning links;
- provide stable content-block types and streaming events.

Frontend responsibilities:
- render supported content-block types;
- render citation markers and source panels;
- handle progressive updates and completed blocks;
- display document links supplied by the backend;
- handle unsupported block types gracefully according to schema-version policy.

LLM responsibilities:
- produce answer content;
- choose among the supplied evidence IDs for citations;
- follow the constrained output schema.

LLM must not:
- write React components;
- decide the frontend's component hierarchy;
- invent source links, document IDs, page numbers, or authorization state;
- produce arbitrary executable HTML/JS as the application response contract.

## 10. Suggested code organization

A modular monolith was suggested as a practical starting point. Keep responsibilities separated without introducing distributed services prematurely.

Possible logical layout (illustrative; adapt to existing repository conventions after inspection):

```text
app/
  generation/
    schemas/
      request.py
      response.py
      events.py
    services/
      generation_service.py
      context_builder.py
      prompt_builder.py
      output_validator.py
      citation_validator.py
    prompts/
      ...
    llm/
      client.py
      providers.py
```

Do not create this structure blindly. First inspect the current repository and reuse existing abstractions where sensible. Avoid duplicating an existing LLM client or schema conventions.

Potential component responsibilities:
- **GenerationService**: coordinates the stages for one generation request.
- **ContextBuilder**: prepares supplied history and evidence for the prompt.
- **PromptBuilder**: builds versioned model input.
- **LLMClient**: abstracts provider invocation and structured output.
- **OutputValidator**: parses and validates response structure.
- **CitationValidator**: checks all evidence references and attaches trusted provenance.
- **SourceResolver**: if needed, resolves authorized document metadata and links outside the model boundary.

These are proposed logical boundaries, not confirmed existing module names.

## 11. Error and status behavior to design

The pipeline should distinguish at least these classes of outcome:
- invalid request / invalid input;
- no usable evidence supplied;
- insufficient evidence for a grounded answer;
- conflicting evidence;
- provider timeout or transient provider error;
- provider/configuration error;
- malformed or schema-invalid model output;
- invalid citation/evidence reference;
- successful completed answer.

Do not collapse all failures into an empty answer or generic success response. Decide which failures are returned as typed statuses and which are raised as application exceptions, then document that behavior in the actual implementation.

For insufficient evidence, prefer an explicit, honest answer/status over fabricated completion. The pipeline should not make unsupported claims merely to fill the response.

## 12. Testing and observability direction

The generation component should be testable without a live retrieval system and, where possible, without a live LLM.

Suggested test layers:
1. Schema tests for valid and invalid requests/responses/events.
2. Unit tests for context preparation and prompt construction.
3. Mock-client tests for successful generation.
4. Output-validation tests for malformed JSON / invalid schema.
5. Citation-validation tests for known, unknown, duplicate, and missing evidence IDs.
6. Grounding behavior tests for empty, irrelevant, and conflicting evidence.
7. Streaming tests for event order, sequence numbers, block completion, and final reconstruction.
8. Provider integration smoke tests kept separate from deterministic unit tests.

Useful operational metadata may include:
- request/response ID;
- model and provider identifiers;
- prompt version;
- latency by stage;
- token usage where available;
- number of evidence items supplied;
- number of citations accepted/rejected;
- final status and error category.

Avoid logging full sensitive document text, secrets, private storage keys, or signed URLs. Logging policy must follow the project's privacy and security requirements.

## 13. Implementation sequence when authorized

A sensible incremental sequence is:

1. Inspect the current repository for existing LLM clients, Pydantic conventions, prompt organization, and service patterns.
2. Finalize the request and response schemas.
3. Implement input validation and context/evidence preparation.
4. Implement prompt construction with versioned prompts.
5. Add or reuse a provider abstraction and a mockable client.
6. Implement a non-streaming generation path first.
7. Add output parsing and citation validation.
8. Add backend source resolution only where the surrounding services can safely support it.
9. Add deterministic unit tests and provider smoke tests.
10. Add typed streaming events and transport integration as a separate increment.
11. Integrate the generation service into the future AI orchestrator only when that later task is explicitly started.

Do not jump directly to the orchestrator, endpoint, or frontend implementation before the independent generation contract and core behavior are stable.

## 14. Decisions, proposals, and unresolved questions

### Explicitly established by the user
- Generation is to be built independently first.
- It receives query, context, and retrieved documents/evidence.
- A separate AI orchestrator will be built later to perform end-to-end work.
- Architecture and the generation block should be considered before the orchestrator.
- The response needs a well-defined structure, including citations and links to documents actually cited.
- The backend should define the schema; the frontend should render according to that schema.
- The generation system should be designed with progressive/streaming output behavior in mind.
- Evaluation documentation is assigned to another agent and is not part of this task.

### Proposed in the architecture discussion (not all finalized)
- Modular-monolith organization.
- Pydantic contracts.
- Provider/client abstraction.
- Versioned prompt templates.
- The seven-stage pipeline in Section 4.
- Typed content blocks, citation/source references, and streaming event envelopes.
- SSE as a possible initial streaming transport.
- Block-level citation association as an initial granularity.

### Questions to resolve before implementation
- What exact conversation-history format and maximum history size should the request accept?
- What is the canonical evidence schema produced by the retrieval layer, and which metadata fields are guaranteed?
- Should the model return structured blocks directly, or should an internal normalized answer be transformed into blocks by backend code?
- Which block types are required for the first release?
- Should citations attach to blocks, sentences, or individual claims?
- What is the policy for unknown citation IDs: fail the response, retry once, or omit invalid citations and mark the result?
- What exact insufficient-evidence behavior/status should the API expose?
- Which existing service should resolve authorized document/version metadata and private download URLs?
- What is the first supported LLM provider/model and its structured-output capability?
- Should streaming begin with token deltas or only emit validated block-level updates?
- Which transport should be used when the API layer is eventually introduced?
- What schema-version compatibility policy should frontend clients follow?

Do not silently decide these questions in implementation. Bring material trade-offs to the user when they affect architecture or behavior.

## 15. Instructions for future agents

Before making changes:
- Read this file in full.
- Inspect the actual repository; this memory records discussion and selected codebase observations, not a substitute for source-code verification.
- Distinguish existing implementation from proposed architecture.
- Preserve the separation between retrieval, generation, and the future orchestrator.
- Do not change evaluation files or perform the separate evaluation-documentation task unless explicitly assigned.
- Do not modify production code until the user explicitly authorizes implementation.
- When implementation is authorized, update this memory only when a decision is confirmed or the architecture materially changes. Keep unresolved questions visibly unresolved.
- Never claim that a proposed schema, module, streaming protocol, or behavior exists in code until verified.

---
End of generation pipeline memory.

## 16. Confirmed end-to-end flow and citation placement (2026-11-04)

This section records the user's confirmed understanding of the end-to-end generation flow. It refines earlier proposals in this memory. It remains an architectural design, not an assertion that the implementation already exists.

### 16.1 Agreed high-level phases

The current simplified pipeline is discussed as these six phases:

1. **Input Validation** — validate the current query, role-based conversation history, and retrieved evidence. Deterministic application code; no LLM call.
2. **Context Preparation** — organize query, history, and evidence; preserve provenance and metadata; assign or preserve request-scoped evidence IDs; manage context-window limits. Deterministic application code; no LLM call.
3. **Generation Agent** — construct the prompt using prompt templates, invoke the LLM, and produce the answer in the agreed structured schema. This is the primary LLM phase. LangGraph is planned for agent/workflow composition, LangChain prompt templates for prompt construction, and Pydantic for structured output validation. Reuse the existing project LLM client and conventions after inspecting the current code.
4. **Citation Validation** — validate generated evidence references against the exact evidence supplied to this request. The user explicitly chose deterministic/rule-based validation to avoid the latency of a second LLM call.
5. **Response Formatting** — resolve validated evidence IDs to trusted backend source metadata and assemble the final response contract. Do not let the LLM invent document URLs, canonical IDs, or authorization state.
6. **Streaming / Delivery** — expose the generated response progressively to the caller/frontend. Streaming is a delivery capability, not necessarily a separate model reasoning phase; it may be implemented alongside the Generation Agent and the response/delivery interface. Begin with a reliable non-streaming path, then add streaming without changing the logical final response schema where possible.

The Generation Agent is the only phase that necessarily invokes the LLM in the initial design. Do not add a second LLM call for citation verification.

### 16.2 End-to-end example: Naruto and Hinata

Illustrative user query:

> Did Naruto marry Hinata?

Illustrative retrieved evidence:

- **E1:** “Naruto became the Seventh Hokage, and afterwards he got married to Hinata.”
- **E2:** “Naruto and Hinata had a small, beautiful family with two children, Boruto and Himawari.”
- **E3:** “Iruka takes on a father-like role in Naruto's life.”

The exact document IDs, page numbers, and source titles must come from the actual retrieval result; any titles/pages used in demonstrations are placeholders, not real metadata.

#### Phase 1 — Input Validation

The application validates the query, history structure/roles, evidence shape, required metadata, and uniqueness of evidence IDs. Invalid input is rejected before model invocation.

#### Phase 2 — Context Preparation

Prepare a context object that keeps the query, history, and evidence separate. Each evidence item has a stable request-scoped evidence ID (for example E1, E2, E3) and retains its trusted metadata (document ID/version, chunk ID, page, source, and other available provenance).

The model sees the evidence IDs and text. The backend retains the authoritative evidence registry for later validation and source resolution.

#### Phase 3 — Generation Agent

The prompt instructs the model to:
- answer using the supplied evidence;
- cite factual claims with only the supplied evidence IDs;
- never invent evidence IDs, document IDs, page numbers, source titles, or URLs;
- avoid unsupported facts and communicate when the evidence is insufficient;
- return the defined structured response.

An illustrative structured result can represent content as ordered text and citation parts:

```json
{
  "blocks": [
    {
      "type": "paragraph",
      "content": [
        {"type": "text", "text": "Yes! Naruto married Hinata after becoming the Seventh Hokage."},
        {"type": "citation", "evidence_id": "E1"}
      ]
    },
    {
      "type": "paragraph",
      "content": [
        {"type": "text", "text": "They later built a family with two children, Boruto and Himawari."},
        {"type": "citation", "evidence_id": "E2"}
      ]
    },
    {
      "type": "paragraph",
      "content": [
        {"type": "text", "text": "Iruka also played an important father-like role in Naruto's life."},
        {"type": "citation", "evidence_id": "E3"}
      ]
    },
    {
      "type": "paragraph",
      "content": [
        {"type": "text", "text": "If you want to know more about their story, I can explain it further!"}
      ]
    }
  ]
}
```

This is illustrative, not a finalized schema. The model's structured output is still untrusted until parsing and validation succeed.

#### Phase 4 — Citation Validation

A deterministic Python validator checks each citation against the evidence registry for the current request. Checks can include:
- the evidence ID exists in the exact evidence set supplied to this generation call;
- the ID maps to the expected original document/version/chunk metadata;
- the citation structure and referenced IDs conform to the schema;
- no unknown/fabricated evidence IDs are accepted;
- provenance is retained and not taken from model-authored source metadata.

A citation to E99, if E99 was not supplied, is invalid and must never be exposed as a verified source.

**Important limitation:** these rules establish citation/reference integrity, not semantic entailment. A rule-based validator can prove that E1 was supplied and that its metadata is authentic; it cannot generally prove that the sentence “Naruto married Hinata” is semantically supported by E1. The user chose no second LLM verifier to reduce latency. Do not describe deterministic ID validation as a guarantee that every claim is factually or semantically grounded.

The precise invalid-citation policy (reject whole response vs. remove/flag invalid citation and mark status) still needs to be finalized. Never silently display an invalid citation as valid.

#### Phase 5 — Response Formatting

The formatter resolves each validated evidence ID using trusted backend metadata. It can build source references containing the actual document title, page/chunk location, and an authorized document link if the backend can safely resolve one. Authorization must be checked before returning private links. If a link cannot be safely resolved, omit the link rather than inventing one.

The model supplies answer text and evidence IDs only. The backend owns canonical source metadata, permissions, and URLs.

#### Phase 6 — Streaming / Delivery

The final logical response is delivered to the chatbot/frontend. A future streaming implementation may send progressive content/block events, but citations and source details should not be presented as verified until the corresponding evidence IDs have passed validation and trusted source resolution. The completed response should be reconstructable from the stream.

### 16.3 Inline citation placement — confirmed UX direction

The user asked where a citation should appear when the answer contains a factual statement followed by a conversational offer.

**Decision:** place each citation immediately after the factual claim or sentence it supports, not at the end of an unrelated conversational sentence or indiscriminately at the end of the whole answer.

Example:

> The annual leave policy provides 20 days of leave [1]. If you want to know more about the policy, I can explain it further.

For multiple claims:

> Employees receive 20 days of annual leave [1]. They can carry forward up to 5 unused days [2]. If you want, I can explain the carry-forward policy further.

The conversational offer normally needs no citation because it is not a factual claim.

For the Naruto example:

> Yes! Naruto married Hinata after becoming the Seventh Hokage [1]. They later built a family with two children, Boruto and Himawari [2]. Iruka also played an important father-like role in Naruto's life [3]. If you want to know more about their story, I can explain it further!

The UI may render [1], [2], and [3] as clickable citation markers, with a source list/panel containing backend-resolved source details. The exact visual interaction is a frontend decision; the backend contract must preserve the precise association between each citation marker and its evidence.

### 16.4 Content representation implication

A plain paragraph string with a list of citations attached only at the end may not preserve the desired claim-level placement. The response contract should support inline citation parts/segments, or an equivalent representation that records the citation's position in the content.

An illustrative paragraph content sequence is:
- text segment: “The annual leave policy provides 20 days of leave.”
- citation segment: evidence ID E1
- text segment: “ If you want to know more about the policy, I can explain it further.”

This allows the frontend to render the citation marker exactly after the supported factual statement. The actual Pydantic schema and renderer contract remain to be designed and verified against frontend needs.

### 16.5 Confirmed latency principle

Avoid an additional LLM call solely to verify citations. Use deterministic application validation for evidence ID integrity, metadata matching, and provenance. Keep semantic entailment limitations explicit in product behavior and documentation. Do not add an LLM verifier unless the user revisits this decision.

### 16.6 Updated decisions

Confirmed by the user:
- Use a six-phase high-level view: Input Validation, Context Preparation, Generation Agent, Citation Validation, Response Formatting, and Streaming/Delivery.
- The Generation Agent is the LLM generation phase; other stages should be deterministic wherever possible.
- Do not use a second LLM call for citation verification; prioritize lower latency.
- Validate citation/evidence IDs with application-side rules.
- Place citations inline immediately after the factual claim/sentence they support.
- Keep conversational follow-up wording separate from factual claims; it usually does not need a citation.
- The Naruto/Hinata example above is the agreed illustrative end-to-end flow.

Still open:
- Exact Pydantic request/response schemas and inline content-part representation.
- Exact behavior when one or more citation IDs are invalid.
- How to represent answers with no citations or insufficient evidence.
- Which metadata fields are guaranteed by retrieval and which source resolver will be used.
- Streaming granularity and transport.
- How to communicate the distinction between valid citation references and semantic support without adding a second LLM call.

## 17. Simplified generation architecture, prompt inputs, evidence policy, and private document citations (2026-11-04)

This section records the latest decisions from the architecture discussion. It **supersedes earlier proposals where they conflict**, especially the separate Input Validation and Context Preparation phases, the general-knowledge fallback proposal, and the earlier assumption that generation should repeat upstream request/evidence validation. This is still architecture memory; it does not claim these features have been implemented.

### 17.1 Generation is downstream of retrieval and reranking

The user clarified that the existing upstream retrieval pipeline receives and validates the user query, retrieves evidence, and applies the established retrieval/reranking stages. Generation is not the application's first entry point and should not duplicate upstream responsibilities.

The upstream retrieval/reranking system is expected to supply:
- the current query;
- optional conversation history, if available;
- the final ranked list of retrieved chunks;
- unique evidence/chunk results;
- chunk text and the trusted metadata needed for source resolution.

The retrieval pipeline remains responsible for query handling, retrieval, hybrid/dense/sparse search, fusion, reranking, adaptive top-K, and its own relevance selection. Generation must not call retrieval itself.

**Do not create a standalone Input Validation phase in the generation pipeline.** Query validity and retrieval-result construction belong upstream. Likewise, do not create a standalone Context Preparation phase merely for architectural formality.

Generation may perform minimal boundary/contract assertions needed to catch integration or programming errors (for example, an unexpected missing field or an unsupported object shape). These are defensive checks, not a second retrieval-validation subsystem and not a separate pipeline stage. Do not revalidate ranking, uniqueness, or query semantics if the upstream contract guarantees them.

Conversation history is optional. Generation must work correctly when history is absent or empty.

A unique reranker output guarantees uniqueness only if the upstream implementation contract says so; uniqueness alone does not prove relevance or sufficiency. Where the retrieval layer provides relevance/confidence/sufficiency signals, generation may use them. Do not invent such signals or assume that a nonempty evidence list is necessarily relevant.

### 17.2 Simplified generation flow

The current recommended high-level flow is:

~~~text
Upstream Retrieval + Reranking
  (query, optional history, ranked unique evidence)
                 |
                 v
1. Generation Agent
   - assemble prompt context
   - include selected evidence metadata and chunk text
   - invoke LLM
   - parse/validate structured output
                 |
                 v
2. Citation Validation
   - verify every evidence ID against this request's evidence registry
   - reject/flag unknown references according to the eventual policy
                 |
                 v
3. Response Formatting
   - resolve evidence IDs to trusted source metadata
   - construct stable application citation/document routes
                 |
                 v
4. Delivery
   - return the structured response
   - add streaming later, without changing the logical response contract
~~~

Prompt-context assembly is part of the Generation Agent, not a mandatory independent phase. The Generation Agent is the only phase that necessarily calls the LLM. Citation validation remains deterministic Python code; do not add a second LLM call for citation verification.

### 17.3 Prompt inputs and metadata policy

The initial prompt should contain clearly separated sections:

1. **System instructions:** assistant role, company-document grounding policy, answer/citation rules, and insufficient-evidence behavior.
2. **Current query:** the current user question.
3. **Conversation history:** optional prior role-based messages, kept separate from the current query and evidence.
4. **Retrieved evidence:** ranked chunks with evidence IDs, content, and only useful descriptive metadata.
5. **Output requirements:** the agreed structured response schema, including inline citation references and answer status.

For each evidence item, the initial recommended prompt-visible fields are:
- request-scoped evidence ID (for example E1);
- chunk/page content;
- document title or source display name, when available;
- page number, when available;
- section heading, when available;
- document date/version information only when relevant to interpreting the question.

Do **not** pass all backend metadata indiscriminately. In particular, do not normally expose:
- storage bucket names, object keys, filesystem paths, or private storage locations;
- signed URLs or other document URLs;
- authorization/permission data;
- database-internal document/version/chunk primary keys unless there is a specific model task that requires them;
- embeddings or raw vector data;
- retrieval/reranker scores by default.

The backend must retain the authoritative evidence registry and full trusted provenance, even when the model sees only a small subset. Evidence IDs are handles that the model can cite; the backend maps them to the actual document/version/chunk records. The LLM must never generate canonical IDs, page metadata, URLs, or permissions.

Illustrative prompt evidence formatting:

~~~text
RETRIEVED EVIDENCE

[E1]
Document: Employee Leave Policy
Page: 4
Section: Annual Leave
Content:
Employees are entitled to 20 days of annual leave per calendar year.

[E2]
Document: Employee Leave Policy
Page: 5
Section: Leave Carry Forward
Content:
Unused annual leave can be carried forward up to a maximum of 5 days.
~~~

The example is illustrative only. Actual titles, pages, sections, and content must be taken from the upstream evidence metadata.

Conversation history should be supplied separately and only when present. It must not be merged into the retrieved-evidence section or treated as trusted company documentation.

### 17.4 Product policy: company-document-grounded assistant initially

The user rejected a general-purpose hybrid chatbot as the initial product direction. SaviraCortex should initially behave as a company-knowledge assistant whose answers are grounded in the company's retrieved documents.

For the first release:
- Company-specific questions must be answered from supplied company evidence.
- Do not use parametric/general model knowledge as a fallback to invent company policies or company facts.
- Do not add an LLM router to choose between RAG and general knowledge. It adds complexity and potentially latency without being needed for the initial product.
- Do not answer a company-specific question from model memory merely because retrieval returned no useful evidence.
- General-knowledge answering is not part of the initial scope. It can be reconsidered later as an explicit product requirement, with a deliberate policy and clear separation from company facts.

The retrieval stack (dense retrieval, sparse retrieval, hybrid retrieval, fusion, reranking, adaptive top-K) exists to find and prioritize the company's relevant evidence. Generation must use that evidence rather than bypass it.

### 17.5 Insufficient-evidence behavior

The initial behavior should distinguish these cases:

1. **Relevant and sufficient evidence:** answer using the evidence and cite factual claims.
2. **Relevant but incomplete evidence:** provide only the supported partial answer, clearly qualify it as incomplete, explain what information is missing when possible, and cite the supported claims.
3. **No relevant evidence:** say that the assistant does not have enough information in the available company documents (a concise “I don't know / I can't determine that from the available documents” response) and invite the user to ask about a topic covered by company information.

Do not force an answer from irrelevant chunks. A nonempty evidence list does not by itself mean evidence is sufficient. Use upstream relevance/sufficiency information if the actual retrieval contract provides it. The user intends to add stronger guardrails in a later implementation increment; the initial prompt should already instruct the model to avoid unsupported company claims and to be honest about missing information, without introducing an extra LLM call or a separate guardrail service at this stage.

The exact machine-readable status names and robust sufficiency decision logic remain implementation details to settle after inspecting actual retrieval outputs.

### 17.6 Clickable citations: backend-owned stable application routes

The user wants citation markers such as [1] to be clickable. Clicking a citation should open the actual original document, preferably at the cited page, inside SaviraCortex's own UI.

The LLM should return only evidence IDs in the answer. The backend:
1. validates the evidence ID;
2. resolves it through the trusted request evidence registry;
3. obtains the canonical document/version identity and page/chunk location from backend metadata;
4. constructs a stable application document route;
5. returns the citation/source data to the frontend.

Do not ask the LLM to generate URLs. Do not expose bucket URLs, bucket names, object keys, or storage paths to the model or frontend.

An illustrative stable route is:

~~~text
/api/gateway/documents/DOC-101/view?page=4
~~~

The actual route shape must follow the existing application routing/API conventions after repository inspection. DOC-101 and the route above are examples, not confirmed production identifiers.

The stable application route is not itself a public file URL. It is an authenticated gateway endpoint. It resolves the document internally using trusted database metadata and the private storage integration.

### 17.7 Private document gateway and in-app viewer

The document bucket must remain private. The preferred design is an authenticated application endpoint that streams the original document to the frontend's in-app document viewer.

Expected request flow:

~~~text
User clicks inline citation
        |
        v
Frontend opens application route / viewer
        |
        v
Authenticated Document Gateway API
        |
        v
Authenticate session
        |
        v
Authorize access to this specific document
        |
        v
Resolve document/version/storage key internally
        |
        v
Read/stream object from private bucket
        |
        v
Render document in SaviraCortex viewer
~~~

Expected access behavior:
- valid session and permission: return/stream the document;
- logged out or expired session: return 401 Unauthorized; frontend can prompt/re-direct to sign in;
- authenticated but not authorized for the document: return 403 Forbidden;
- missing document: return 404 Not Found.

Authorization must be checked when the document is opened, not only when the original answer is generated. A retrieved chunk does not automatically grant permission to open its parent document. Apply organization/document access controls on every document request. Avoid leaking whether an inaccessible document exists where the application's security policy requires a non-disclosing response.

The viewer should ideally open within the existing chat UI (a side panel is the preferred UX direction, although exact UI design is a frontend decision) and navigate to the cited page when the file format and viewer support it. For PDF viewing, a frontend PDF viewer such as PDF.js is one possible implementation; confirm existing frontend conventions before selecting a library. Support HTTP Range requests if needed for efficient PDF navigation/partial loading.

### 17.8 Temporary signed URLs

A signed object-storage URL is an optional implementation mechanism, not the preferred browser-facing citation URL.

The user prefers the authenticated application gateway because:
- the bucket remains private;
- copied application links still require a valid application session and document authorization;
- the application can log and control document access;
- no temporary storage URL needs to be exposed in the citation response.

The backend may still generate/use a short-lived signed URL internally if the storage provider integration requires it, but it should not return that signed URL to the browser in the preferred gateway design. If a signed URL is ever returned to the browser as an alternative, understand that anyone possessing it can generally use it until expiry; it is a bearer capability and is not inherently restricted to the application UI.

The previously inspected project memory records a private B2 storage integration and FileStorage.generate_download_url(storage_key, expiration_seconds=900). Verify the current code and actual storage provider before implementation; do not assume this method must be used. The gateway can instead stream through the existing storage client. Never expose the storage key.

### 17.9 Responsibility boundaries

| Component | Responsibility |
|---|---|
| Upstream retrieval/reranking | Query processing, dense/sparse/hybrid retrieval, fusion, reranking, adaptive top-K, ranked unique evidence |
| Generation Agent | Prompt context assembly, prompt construction, LLM invocation, structured output parsing |
| Citation Validator | Deterministic validation of model-returned evidence IDs |
| Response Formatter / Source Resolver | Resolve validated IDs to trusted document metadata and stable application routes |
| Document Gateway API | Authenticate, authorize, retrieve and stream private documents |
| Frontend | Render answer/citations and open the document in the in-app viewer |
| Future AI orchestrator | Coordinate the end-to-end workflow; explicitly out of scope for this initial generation implementation |

The document gateway is a separate application/document-access concern. It is not another generation phase and should reuse existing authentication, authorization, database, and storage services where possible.

### 17.10 Current implementation sequence

When the user authorizes coding:

1. Inspect the actual repository and current retrieval output contract. Confirm the exact fields and metadata guarantees rather than inventing an incompatible evidence schema.
2. Inspect existing LLM clients, Pydantic conventions, prompt patterns, and dependency versions. Reuse project abstractions.
3. Finalize the minimal generation input contract: query, optional history, ranked evidence, and trusted provenance.
4. Define the structured generation output with inline citation parts and an answer/insufficiency status.
5. Implement the Generation Agent: assemble prompt context, apply the company-grounded prompt, invoke the existing LLM client, parse output.
6. Implement deterministic citation ID validation against the request evidence registry.
7. Implement response formatting and source resolution using trusted backend metadata. Do not fabricate URLs.
8. Test sufficient, partial, no-relevant-evidence, malformed-output, and invalid-citation cases.
9. Keep streaming as a later increment after the non-streaming response contract is reliable.
10. Inspect the existing document catalogue, private B2 storage, authentication, and authorization code before implementing or modifying any document gateway/viewer integration. Do not duplicate existing document APIs or auth mechanisms.
11. Keep the future orchestrator out of scope.

### 17.11 Latest decisions and remaining implementation questions

**Confirmed direction:**
- Remove standalone generation Input Validation as a phase; upstream owns query/retrieval validation.
- Remove standalone Context Preparation as a phase; prompt-context assembly belongs inside Generation Agent.
- History is optional.
- Generation receives the final ranked, unique evidence list from upstream and does not rerun retrieval or reranking.
- Keep only lightweight defensive boundary checks as needed to catch contract/integration bugs.
- Prompt contains system instructions, current query, optional history, retrieved evidence, and output requirements.
- Pass evidence IDs, chunk content, and selected descriptive metadata (title, page, section when available); retain full provenance in backend.
- Do not pass bucket/storage internals, private URLs, authorization data, embeddings, or unnecessary internal IDs/scores to the LLM.
- Initial product policy is company-document-grounded answers only; no general-knowledge fallback and no LLM router.
- Relevant but incomplete evidence can produce a qualified partial answer with citations.
- No relevant evidence should produce an honest “I don't know / not available in company documents” response and invite a related company-information question.
- Stronger guardrails can be improved later; do not add another LLM call now.
- Citations are inline, immediately after the factual claim they support.
- The LLM outputs evidence IDs only; backend validates and resolves them.
- Use stable application citation/document routes, not raw bucket URLs.
- Keep the bucket private.
- Prefer an authenticated document gateway endpoint that checks session and document authorization on every request and streams the document to an in-app viewer.
- Expired/logged-out sessions should fail authentication; unauthorized document access should be denied.
- Temporary signed URLs are optional for internal backend use, not the preferred browser-facing citation link.
- Streaming is a later enhancement; establish the non-streaming contract first.
- Do not build the AI orchestrator as part of this generation implementation.

**Still to confirm after repository inspection:**
- Exact retrieval evidence schema and guaranteed metadata fields.
- Whether the upstream retrieval layer exposes relevance/sufficiency signals and how to interpret them.
- Exact response schema and answer-status enum.
- Invalid citation policy (fail whole response vs. suppress/flag invalid citations).
- Actual storage provider and current storage API details (existing project notes mention private B2; verify current implementation).
- Existing document gateway, authentication, authorization, and frontend viewer capabilities to reuse.
- Whether cited-page navigation is supported by the existing viewer.
- Streaming protocol and event granularity for the later streaming increment.

Do not start coding from assumed field names or a guessed storage/API design. Inspect the codebase first, then present the concrete input/output contract and implementation plan for confirmation where material choices remain.
