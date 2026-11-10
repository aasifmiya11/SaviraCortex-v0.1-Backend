# 34. Guardrails Architecture Decisions

**Status:** Architecture agreed in discussion; implementation not yet started for the runtime input/output guardrail layers described here. Existing document-level prompt-injection protections remain implemented as documented in [33 — Security Guardrails Architecture](33-security-guardrails-architecture.md).
**Decision date:** 10 November 2026
**Scope:** Multi-tenant input guardrails, topicality routing, output guardrails, tenant policy configuration, and enforcement boundaries.

> This document records the current working architecture decisions. It is not evidence that the proposed runtime layers are implemented or tested. Thresholds and classifier behavior are initial design choices that must be calibrated before production use.

## 34.1 Architectural name and principle

The overall capability is called **SaviraCortex Guardrails Architecture**. It is a layered, policy-driven guardrail system for a multi-tenant chatbot/RAG platform.

Core principle:

- Prefer established libraries and deterministic methods for checks that do not require generative semantic reasoning (for example, PII recognition, pattern/secret scanning and format validation).
- Use the existing JEV integration as the semantic judge for checks that benefit from contextual reasoning.
- Keep detection/classification separate from policy enforcement and routing.
- Keep tenant-specific behavior configurable, while preserving mandatory SaviraCortex platform security controls.
- Reuse the existing compiled agent graph; add guardrail decisions at explicit middleware/conditional graph boundaries rather than replacing the graph.

JEV is a classifier/judge, not the policy authority, authorization system, or graph router. Its typed result is evaluated by application policy code.

## 34.2 Existing document-level protection

Document prompt-injection protection is an existing implementation, not part of the new runtime work in this decision:

- Uploaded document content is inspected during ingestion using the existing JEV document-level integration.
- The ingestion review flow supports rejecting a document, safely ingesting while excluding flagged chunks, or explicitly ingesting anyway.
- Retrieved document text is treated as untrusted evidence/source material, never as system/developer instructions or executable commands.
- The retrieval/generation trust boundary instructs the agent not to follow instructions embedded in retrieved content.

See [33 — Security Guardrails Architecture](33-security-guardrails-architecture.md) for implementation details and verification boundaries. A user/uploader override to ingest flagged content does not grant that content instruction authority.

## 34.3 Tenant policy configuration

SaviraCortex is a multi-tenant chatbot platform. Each organization will be able to configure its chatbot behavior through organization-level settings, including:

- Custom system prompt / chatbot identity and behavior.
- Allowed topics and, where needed, restricted topics.
- Input guardrail policies.
- Output guardrail policies.
- Per-category enforcement actions and custom redirect/error messaging.

Keep platform defaults separate from organization configuration. Resolve the applicable settings into an **effective policy snapshot per request** and use that same snapshot for the request's input, streaming-output and final-output decisions. This prevents policy changes during a stream from causing inconsistent segment decisions.

Policy precedence:

1. Mandatory SaviraCortex platform security requirements cannot be disabled by a tenant.
2. Where a tenant has configured an allowed override, use its organization-level setting.
3. Where the tenant has not configured a category/action, use the SaviraCortex default.

Input and output policies remain distinct because the risks and actions differ. They may share schemas, detector adapters and an enforcement framework, but an input rule is not automatically an output detector.

## 34.4 Input guardrails

The planned runtime input flow runs before the request enters retrieval/answer generation.

### 34.4.1 Request validation

Perform basic deterministic validation and normalization: request shape, encoding, size limits and other API constraints. Do not normalize in a way that changes the user's intent.

### 34.4.2 PII detection and user choice

Use an established non-generative PII library (Presidio is the current candidate) rather than writing and maintaining general-purpose PII recognizers ourselves.

When PII is detected in the current user input, pause before passing the original input to the agent and present the user's configured consent choices, initially:

- **Redact and send:** replace detected values with appropriate placeholders and proceed with the redacted input.
- **Send as-is:** proceed with the original input only after explicit user confirmation, subject to platform and organization policy.
- **Reject:** cancel the request without sending it to the agent.

The original PII-bearing input must not reach the agent before the user's decision. Tenant configuration may define permitted handling, but cannot override mandatory platform restrictions.

### 34.4.3 Semantic safety classification with JEV

Use JEV for contextual/semantic categories where simple patterns are insufficient. Pass:

- The current user message as the primary classification target.
- A configurable, recent sliding window of conversation history (initial proposal: the previous five user/assistant exchanges).
- Clearly separated fields for current message and historical context.

Conversation history is **untrusted context**, not a system prompt and not an instruction source. The current message is the primary target; history helps interpret meaning. A historical violation should not automatically make every later message unsafe.

Initial independent classification categories:

- Direct jailbreak.
- Indirect prompt injection / untrusted instruction attempts.
- Role manipulation.
- System-prompt or instruction extraction attempts.
- Toxicity / harassment / abusive content.
- Sexual content, with legitimate educational, medical and informational discussion distinguished from disallowed content.
- Hate speech and discrimination, including religious or ethnicity-targeted hatred (do not classify discussion of a religion or ethnicity itself as hateful).
- Violence and self-harm.
- Organization-specific prohibited content/policy categories, as configured.

The judge should return a structured result with independent per-category fields such as triggered status, category, concise reason and confidence. A message may trigger multiple categories. The application, not JEV, maps these results to actions.

### 34.4.4 Topicality and conditional routing

Topicality is an application-scope decision, not a safety violation. Each organization configures its allowed topics. The classifier evaluates the current query against those topics, using relevant conversation context where needed.

Initial proposed hybrid approach:

- Compute semantic similarity between the query and the organization's topic descriptions.
- **Above 60%:** classify as on-topic and continue, subject to all other guardrails.
- **Below 20%:** classify as off-topic and use the organization's configured off-topic response.
- **20% through 60%:** send the ambiguous case to JEV for contextual topicality classification.

These are initial thresholds, not production-calibrated probabilities. Embedding similarity is a relevance signal, not a calibrated probability. Calibrate thresholds against representative tenant queries, including paraphrases, adjacent topics, short queries and multi-turn follow-ups. Compare against multiple topic descriptions rather than relying on one phrase.

JEV returns a topicality classification/reason for ambiguous cases. A conditional node in the existing compiled graph routes the result:

- On-topic -> continue into the existing agent/retrieval graph.
- Off-topic -> return a gentle organization-configured redirect/response.
- Uncertain -> use the configured clarification/fallback behavior rather than silently assuming either class.

Topicality must not bypass jailbreak, content-safety, PII, authorization or other guardrails. An on-topic request can still be unsafe.

## 34.5 Input decision and enforcement boundary

The input guardrail detectors produce structured findings. A custom policy-enforcement layer applies the effective policy and returns a controlled outcome, for example allow, redact, request confirmation, block, clarify or redirect.

The custom enforcement/routing code—not JEV—decides whether retrieval and the compiled graph may execute. A blocked request must not proceed to answer generation. Retrieval authorization remains independent and must never be delegated to a safety classifier.

## 34.6 Output guardrails

Output guardrails inspect what the agent generates before it is delivered. They run at **both** stages:

1. **Streaming inspection:** inspect generated segments before releasing them to the user.
2. **Final-response inspection:** inspect the complete accumulated response after generation, to catch issues that require wider context.

Initial output detection categories:

- PII leakage (for example, Presidio).
- Secrets and credentials (API keys, access tokens, passwords, private credentials; use dedicated secret/pattern scanning where appropriate).
- System prompt, hidden instruction or internal configuration leakage.
- Unsafe instruction compliance (whether the assistant's response complied with an unsafe request or untrusted instruction).
- Toxicity, harassment, hate/discrimination, sexual content, violence and self-harm.
- Off-topic responses relative to the organization's configured topics, when that organization enables scope enforcement.
- Hallucination / factual grounding against retrieved evidence and permitted sources.
- Organization-specific output policy violations.

Some categories can reuse input-side detector adapters, but output-specific policies and validation semantics remain separate. Grounding/hallucination checks require comparison with evidence and cannot be reduced to a generic toxicity or jailbreak classifier.

### 34.6.1 Default and tenant-configured actions

The safe platform default is to **stop delivery when an output violation is detected**. Organizations may configure permitted per-category actions in their settings, such as:

- Mask/redact a detected span.
- Hash a value where appropriate (hashing is not equivalent to anonymization and may remain linkable).
- Stop/block or hide the response.
- Return a redirect or configured safe message.
- Return a policy error.

Mandatory platform security rules remain non-disableable. The enforcement layer applies the effective policy snapshot for the request.

### 34.6.2 Streaming safety invariant

A segment must be checked before it is released. If a violation is detected mid-stream, stop further delivery by default and apply the configured action.

A final full-response check cannot retract content that has already been sent. If a policy requires a guarantee that no part of a response is exposed before full-response validation, the response must be buffered until final validation completes. This trade-off must be explicit in the implementation and product configuration; do not claim that final validation can undo prior streaming exposure.

If content is transformed (for example, masked), validate the transformed content again before delivery.

## 34.7 Policy enforcement, audit and observability

Use a shared policy-enforcement framework with separate input and output effective policies. Detection components should return structured findings; enforcement maps findings to permitted actions.

Record privacy-conscious audit metadata, such as tenant/request identifiers, detector/category, decision, policy action, stage (input, streaming, final), timestamp and classifier version where available. Do not log raw secrets or unnecessary PII/document content. Apply tenant-scoped access controls and retention rules to audit records.

## 34.8 Implementation boundaries and proposed order

The following are architecture decisions/proposals, not claims of implementation:

1. Inspect current runtime request and compiled-graph integration points before editing code.
2. Define typed schemas for effective tenant policy, detector findings, per-category JEV decisions and enforcement outcomes.
3. Add deterministic request validation and PII detection/consent flow.
4. Add JEV runtime semantic classification with bounded untrusted conversation context and independent categories/reasons.
5. Add organization topic configuration, semantic-similarity topicality, calibrated thresholds and JEV fallback.
6. Add the conditional routing node while preserving the existing compiled graph.
7. Add output detectors, organization-configurable enforcement and safe streaming behavior.
8. Add full-response validation, grounding checks, privacy-conscious audit events and tenant-isolation tests.
9. Test false positives/negatives, ambiguous topicality, multilingual/educational content, policy overrides, classifier failures, streaming interruption and final-validation behavior.

Before implementation, inspect the current code and tests. Do not assume that a discussed library, schema, middleware or graph node already exists. Do not replace the existing agent graph or document-level JEV path without a demonstrated need.

## 34.9 Open implementation details

The following remain to be decided and verified during implementation:

- Exact JEV category taxonomy, typed schema, score semantics and confidence calibration.
- JEV timeout/retry/failure behavior for each operation.
- Which deterministic libraries are selected for each non-LLM category beyond the current Presidio candidate.
- Whether the initial five-exchange context window should be token-bounded and how truncation preserves the current message.
- Similarity model, topic representation, aggregation method and calibrated thresholds.
- Tenant policy schema, versioning, inheritance, permitted overrides and dashboard UX.
- Which output actions are allowed per category and which are mandatory platform blocks.
- Whether output streaming uses segment buffering, sentence buffering or another safe release unit.
- Grounding evaluator design and behavior when retrieval evidence is missing or conflicting.
- Audit retention, privacy and access controls.

## 34.10 Security invariants

- Retrieved documents and conversation history are untrusted data, never instruction authority.
- JEV is a judge, not an authorization mechanism or policy authority.
- A passing topicality result never bypasses other guardrails.
- A passing safety result never grants access to data, documents or tools.
- Tenant/document authorization is enforced independently of model judgment.
- The same effective policy snapshot governs a request's input, streaming and final output checks.
- Do not release a streaming segment before its required checks complete.
- Do not log raw secrets or unnecessary sensitive content.
- Document proposed capabilities as planned until code, tests and end-to-end behavior verify them.


## Implementation tracking — 10 November 2026

The first implementation pass is in progress in these areas:

- Shared effective-policy schema and resolver with platform-enforced mandatory protections.
- Presidio-based input PII consent/redaction before conversation persistence.
- JEV runtime classification with per-category reason codes and confidence, using bounded untrusted conversation history.
- LangGraph conditional routing before retrieval for blocked and out-of-scope inputs.
- Sentence-buffered streaming output checks plus complete-response final validation.
- Tenant-owned policy fields and dashboard controls for topics, custom input/output rules, category actions, PII consent, and topicality thresholds.
- Privacy-conscious guardrail audit events and owner/admin audit view.

The implementation deliberately keeps document-ingestion prompt-injection protection intact. Runtime input/output guardrails are separate layers and do not replace the existing ingestion/retrieval trust boundary.

See backend/docs/33-security-guardrails-architecture.md for runtime details and current safety limitations. Frontend design and interaction contracts are in frontend/DESIGN.md and frontend/UX-CONTRACT.md.


### Conversation-store decision (implemented)

A guardrail block is a first-class assistant turn, not a transient HTTP/SSE error. LangGraph produces the input-block response, and the persistence service records blocked decisions in both the graph checkpoint and `conversation_messages`. Output blocks are normalized to the same persisted assistant-turn shape. The effective redacted user message is the only input stored or passed to LangGraph; its message metadata and graph state identify the `redacted` decision. The chat history endpoint hydrates these fields so the UI can render the decision directly beneath the matching user message after reload.

## 34.11 Organization-configurable output streaming strategies — decision (10 November 2026)

The platform default remains the existing strict check-before-display strategy. Organization owners/admins may select one of three output release strategies for new requests:

1. **Strict segment mode (platform default):** accumulate a bounded segment, inspect it, and only then release it. This is the existing safe behavior.
2. **Optimistic mode:** stream generated content immediately while a separate bounded background evaluator reviews it. A violation produces a server suppression/retraction event tied to stable message and segment identifiers. The UI removes or replaces affected content and generation is stopped or handled according to enforcement policy. This is best-effort UI retraction, not prevention of exposure; already seen/copied content cannot be recalled.
3. **Bucket mode:** accumulate generated tokens in a bounded bucket, inspect the complete bucket, release it only when approved, then clear it and repeat. The effective policy includes minimum and maximum token thresholds. A maximum prevents unbounded buffering; final partial buckets must also be checked before release.

### Mandatory security invariants

- Secret/credential detection and other platform-mandated sensitive-data protections remain pre-display in every mode. Optimistic mode cannot bypass this gate.
- Full-response validation remains enabled in all modes.
- The same versioned tenant policy snapshot is used for the entire request.
- Bucket sizes are bounded by platform limits; minimum must not exceed maximum.
- Optimistic suppression events are scoped to a request/message and stable segment IDs. They must not remove content from another request.
- A final validation failure after prior streaming triggers response-level suppression where possible, but must not be represented as retroactive prevention.
- Organization mode changes affect new requests only.

### Initial settings

- `output_streaming_mode`: `segment` (default), `optimistic`, or `bucket`.
- `output_bucket_min_tokens`: 128 by default.
- `output_bucket_max_tokens`: 512 by default.
- Platform limits: minimum 16 and maximum 16384 tokens.

The implementation is staged: policy/schema and administrator controls are introduced first; streaming execution, safe secret preflight, suppression event protocol, and end-to-end behavior must be completed and tested before optimistic or bucket mode is advertised as production-ready.

## 34.12 Vercel AI SDK UI adoption — implementation decision (10 November 2026)

**Decision:** Adopt Vercel AI SDK UI for the React chat interaction layer while retaining SaviraCortex's existing Python/FastAPI generation architecture.

### Scope

- Frontend dependencies: `ai` and `@ai-sdk/react`.
- `useChat` owns client-side UI message state, submission/streaming/ready/error lifecycle, cancellation, and stream consumption.
- A Next.js `/api/chat` adapter translates the existing FastAPI SSE events into the AI SDK UI message-stream protocol.
- The adapter forwards the Firebase bearer token and organization/conversation/request identifiers. FastAPI continues to verify Firebase identity and organization membership; the frontend-supplied organization ID is never treated as authorization.
- Existing API generation, conversation history, citation, feedback, PDF source, PII consent, and persistence endpoints remain in place.

### Deliberately retained custom behavior

The SDK is the chat lifecycle and message-stream foundation, not the SaviraCortex product policy or visual system. Custom behavior remains for:
- PII consent, redaction, and idempotent retry using the original request and user-message IDs.
- Streaming status and error data parts.
- Server-approved provisional text and replacement with the final validated response.
- Guardrail decision/category rendering, citation navigation, feedback controls, markdown presentation, and PDF source viewing.
- Future identified segment/bucket parts and suppression updates required by optimistic and bucket output strategies.

Custom data parts are transient where they carry request-time status or consent events. Final generation metadata is attached to the assistant UI message. Ordinary append-only text is not sufficient for future optimistic retraction; that work must use stable segment/bucket identifiers and explicit update/suppression parts.

### AI SDK Core boundary

AI SDK Core is **not** introduced in this migration. Current text generation, structured output, and the RAG workflow already execute in Python/LangGraph. Moving those operations to TypeScript would add a second model-execution runtime without a current capability requirement. Core may be evaluated later for image, speech, embeddings, or tool operations if it provides a concrete benefit, without changing the decision to keep authorization, tenant policy, RAG, and guardrails in the Python backend.

### Verification status

The first frontend integration pass is implemented. TypeScript and targeted ESLint checks pass. Full chat-flow verification against a running authenticated FastAPI/database/LLM stack remains required before the migration is considered end-to-end complete. No claim is made that optimistic or bucket execution modes have been implemented by this UI integration.


## 34.13 Independent organization guardrail master switches — 10 November 2026

Organizations can independently disable their configurable input checks and configurable output checks using `input_guardrails_enabled` and `output_guardrails_enabled`. Both default to enabled. The settings are stored in the effective tenant policy and apply to newly started requests; active requests retain their policy snapshot.

When input guardrails are disabled, tenant-configurable semantic classifications, topicality evaluation, and custom input policy instructions are skipped. Input PII detection/consent handling and platform-required direct/indirect prompt-injection checks remain active.

When output guardrails are disabled, tenant-configurable semantic classifications, grounding/off-topic review, and custom output policy instructions are skipped. Platform-required PII leakage, secret/credential leakage, and hidden system-prompt protections remain active, including pre-display checks.

These are tenant-level opt-outs from organization-configurable policy enforcement, not a global bypass of platform security controls. Per-category settings remain stored and take effect again when the corresponding master switch is re-enabled.


## 34.14 Independent ingestion and retrieval guardrail switches — 10 November 2026

Two additional tenant-level switches are available: `ingestion_guardrails_enabled` and `retrieval_guardrails_enabled`. Both default to enabled and are stored in the same organization guardrail policy.

- Ingestion OFF: skip document prompt-injection inspection during PDF analysis/staging. File type/size validation, authorization, duplicate handling, indexing and other ingestion functions continue. The staged security review is marked `disabled`.
- Retrieval OFF: bypass filtering of ingestion-flagged prompt-injection chunks after authorized retrieval. Such chunks may proceed into context construction and generation.
- Retrieval ON: exclude chunks whose indexed metadata has `prompt_injection_flagged=true` before compression/context construction and generation.
- Policy is resolved from the authenticated organization on upload and from the request policy snapshot in RAG retrieval. Changes affect new ingestion sessions/requests, not already staged reviews or active request snapshots.

These are explicit tenant opt-outs from the corresponding document-pipeline guardrail stages. They do not disable authentication, organization membership/ACL enforcement, upload validation, or other core application controls. Disabling ingestion checks does not retroactively reprocess existing documents.




### 34.13 Output guardrail master switch semantics

When an organization disables output guardrails, the output inspection stage is bypassed end-to-end. This includes per-segment PII/secret detection during streaming and the final whole-response output inspection. Streamed content is emitted without output guardrail detector latency or suppression. When the switch is enabled, platform-mandated PII, secret and system-prompt disclosure checks remain enforced regardless of per-category settings. This switch does not disable independent input, ingestion, retrieval, authentication, authorization or response-schema validation.
