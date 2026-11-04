# 10. AI Agents and LLM Workflows

Six LLM agents are present under `app/agents/`. They are independently implemented components with explicit inputs and structured outputs. The multi-query generator uses LangGraph internally; the document summarizer, Evidence Evaluator, Retrieval Expansion Agent, Context Compression Agent, and Generation Agent use direct prompt/model/parser chains.

## Document summarizer

`app/agents/Document_summarizer/agent.py` implements a stateless `DocumentSummarizerAgent`. It accepts sampled LangChain `Document` pages, rejects empty input, combines non-empty page text into a prompt, invokes a structured-output chain, and returns a validated `DocumentSummarizerOutput`.

The output schema requires four string fields: `title`, `document_type`, `description`, and `summary`; extra fields are forbidden and strings are stripped. The default configuration is a 500-character summary target, descriptive/technical style, English, temperature 0.2, and 2,000 output tokens. The default path uses `SummarizerLLMClient` and a LangChain Pydantic output parser. An optional injected OpenAI-compatible client path parses JSON and validates it with the same Pydantic schema. This agent does not access PostgreSQL, Qdrant or file storage.

## Multi-query generator

`app/agents/Multi_query_generator/agent.py` implements `MultiQueryGeneratorAgent` as a one-node LangGraph (`START -> generate_queries -> END`). The node invokes a prompt/model/Pydantic parser chain. The agent supports synchronous `generate()` and asynchronous `agenerate()`, accepts conversation history and an `AvailableDocuments` catalogue, rejects empty queries, and returns at most six queries by default.

Each generated query has a text query, a version scope (`active`, `superseded`, or `both`), and optional target version years. Pydantic schemas reject extra fields, empty/duplicate query strings, invalid years, and inconsistent active/superseded catalogue entries. The agent additionally verifies that target years exist in the catalogue and belong to the declared scope.

## Evidence Sufficiency Evaluator

`app/agents/Evidence_evaluator/agent.py` implements a stateless `EvidenceEvaluatorAgent`. It accepts the original current query, accumulated retrieved candidates, and optional chronological LangChain conversation messages. It prepares an ordered, prompt-safe representation of usable candidate text and selected descriptive metadata, then invokes a structured prompt/model/Pydantic-parser chain.

The output schema, `EvidenceEvaluation`, contains:

- `is_sufficient`: true only when the retrieved evidence supports every material requirement in the current question.
- `missing_information`: specific requirements that remain unsupported; this list must be empty when evidence is sufficient and non-empty when it is insufficient.

Conversation history helps resolve references but is not treated as factual company evidence. The evaluator checks multi-part and comparative questions for complete coverage, does not answer the user, does not generate retrieval queries, and does not perform retrieval. If no usable evidence is available, it returns a deterministic insufficient judgment without an LLM call. The default configuration uses temperature 0.0 and 1,500 output tokens through the dedicated `EvidenceEvaluatorLLMClient`.

The workflow wrapper in `app/workflows/rag/nodes/evidence_evaluator.py` receives an injected agent, passes the original query, accumulated documents, and optional history to `aevaluate()`, and maps the result to `is_sufficient`, `missing_information`, and `retry` graph-state updates. Retry-limit routing remains a workflow responsibility; the agent does not know or manage the retrieval-attempt limit.

## Retrieval Expansion Agent

`app/agents/Retrieval_expansion/agent.py` implements a stateless `RetrievalExpansionAgent`. It accepts the original user query, the current retrieval query, the evaluator's missing-information requirements, accumulated retrieved candidates, and optional chronological LangChain conversation messages. It prepares prompt-safe evidence from candidate text and selected descriptive metadata, then invokes a structured prompt/model/Pydantic-parser chain.

The output schema, `RetrievalExpansionOutput`, contains:

- `rewritten_query`: a standalone retrieval query focused on the specific missing requirements, preserving the original question's intent and constraints.
- `hypothetical_answer`: a concise hypothetical answer-shaped passage that supplies additional semantic language for retrieval.

The hypothetical answer is retrieval guidance only. It is not verified evidence, must not be cited, and must never be passed to Generation as factual support. The prompt directs the agent to avoid inventing company-specific values, dates, names, or procedures. Previously retrieved content is included to reduce redundant searches; internal IDs, scores, storage details, and permissions are excluded. The agent supports synchronous `expand()` and asynchronous `aexpand()`.

The workflow wrapper in `app/workflows/rag/nodes/retrieval_expansion.py` receives an injected agent, passes the original query, previous rewritten query (or original query on the first expansion), missing requirements, accumulated documents, and optional history, then writes the two outputs into graph state. The wrapper does not enforce the retry limit: graph routing must check the maximum of three total retrieval attempts before invoking this node. The dedicated `RetrievalExpansionLLMClient` defaults to temperature 0.2 and 1,800 output tokens.

## Context Compression Agent

`app/agents/Context_compression/` implements a stateless `ContextCompressionAgent`. It receives the current query and all accumulated retrieval candidates in their existing order. When the estimated context size exceeds the configured threshold, it sends every candidate's content and a one-based index in a single structured model request.

The output schema contains one compressed passage per input index. The agent rejects missing, duplicate, extra, or reordered indexes. It copies each original candidate and replaces only `page_content`; metadata, chunk identity, other retrieval fields, count, and order remain unchanged. The original candidates are never mutated. The model is not given backend metadata, internal IDs, retrieval scores, storage locations, or authorization data.

The default threshold is 12,000 estimated tokens. The current deterministic estimate is `ceil((query and page-content character count) / 4)`; this is a routing estimate, not provider tokenizer accounting. The threshold and characters-per-token factor are configurable. The workflow adapter in `app/workflows/rag/nodes/context_compression.py` skips the model call below the threshold and writes the selected evidence view to `context_documents`. Original `retrieved_documents` remains available to Retrieval Expansion. Evidence Evaluation, Generation, and Static Validation use `context_documents` when present, with fallback to the original list, so Generation and Static Validation share the exact same evidence order and metadata registry. See [Context Compression](29-context-compression.md).

## Generation agent

`app/agents/Generation/agent.py` implements a stateless company-grounded `GenerationAgent` as a direct LangChain prompt/model/Pydantic-parser chain. It accepts the current query, optional chronological LangChain conversation messages, and the retrieval service's final `selected_candidates` list. It preserves candidate order, skips candidates without usable text, assigns request-scoped evidence IDs (`E1`, `E2`, ...), and exposes only chunk text plus selected descriptive metadata to the prompt. Internal IDs, retrieval scores, storage details and permissions are excluded.

The prompt treats retrieved company evidence as the factual basis for company-specific answers. Conversation history may resolve references but is not authoritative evidence. The output uses `GenerationStatus` (`answered`, `partial`, or `insufficient_evidence`) and ordered `AnswerSegment` objects containing text and evidence-ID citations. Both synchronous `generate()` and asynchronous `agenerate()` are available. If no usable evidence remains after preparation, the agent returns a deterministic insufficient-evidence response without invoking the model.

`GenerationConfig` defaults to temperature 0.1 and 5,000 output tokens. `GeneratorLLMClient` uses the existing `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_API_KEY` settings. The agent delegates request-scoped citation-ID existence checks to `app.validation`. The separate Static Validation Layer can validate a complete output and map cited IDs to allowlisted document/version/page metadata when given the original ordered retrieval candidates. Neither component performs semantic claim-to-source verification, resolves viewer URLs, opens documents, or orchestrates other components. The injected LangGraph adapter in `app/workflows/rag/nodes/generation.py` calls `agenerate()` and stores the result in `generation_output`. The separate `create_static_validation_node()` adapter wraps the existing `StaticValidationLayer`, passing the same ordered retrieved candidates and storing its result in `validation_result`. See [Generation pipeline](26-generation-pipeline.md) and [Static validation](27-static-validation.md).

## LLM client defaults

| Client | Temperature | Output token default |
|---|---:|---:|
| Summarizer | 0.2 | 2000 |
| Multi-query | 0.2 | 1500 |
| Evidence evaluator | 0.0 | 1500 |
| Retrieval expansion | 0.2 | 1800 |
| Retrieval | 0.0 | 1500 |
| Generator | 0.1 | 5000 |
| General `LLMClient` | Provider default | Not set here |

All specialized clients use `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_API_KEY`. Structured validation constrains output shape but cannot guarantee semantic correctness. Document content is sent to the configured model provider when these workflows run; assess provider privacy and retention settings accordingly.
