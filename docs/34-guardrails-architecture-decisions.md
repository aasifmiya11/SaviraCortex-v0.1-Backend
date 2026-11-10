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
