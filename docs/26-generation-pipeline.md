# 26. Generation Pipeline

## Purpose and scope

The Generation module produces a structured, company-document-grounded answer from a current user query, optional conversation history, and the final ranked retrieval candidates. It is a standalone generation component; it does not orchestrate the end-to-end application workflow.

The implementation described here is present in:

- `app/agents/Generation/`
- `app/llm/generator_client.py`
- `app/workflows/rag/nodes/generation.py`
- `tests/agent/test_generation.py`
- `tests/workflows/test_generation.py`

This page documents the current code, not planned functionality. Request-scoped citation-ID existence checks and Generation streaming are implemented. Semantic claim-to-source verification, citation-to-document resolution, protected document viewing, and HTTP/API integration remain outside the current implementation. The end-to-end LangGraph RAG workflow itself is implemented in `app/workflows/rag/graph.py` and documented below.

## 26.1 Package structure

```text
app/
├── agents/
│   └── Generation/
│       ├── __init__.py
│       ├── agent.py
│       ├── config.py
│       ├── prompts.py
│       └── schemas.py
└── llm/
    └── generator_client.py

tests/
└── agent/
    └── test_generation.py
```

The package follows the existing agent convention of separating agent behavior, configuration, prompts, schemas, and the LLM client. The project already uses `app/llm/` for model clients, so the generation client is placed there rather than introducing a new `app/llm_factory/` package.

## 26.2 Responsibilities and boundaries

The Generation Agent:

1. Receives the current query.
2. Receives optional chronological LangChain conversation messages.
3. Receives the retrieval service's final `selected_candidates` list in its existing order.
4. Converts usable candidates into a prompt-safe evidence representation.
5. Assigns request-scoped evidence references (`E1`, `E2`, ...).
6. Invokes one prompt/model/parser chain.
7. Returns a Pydantic `GenerationOutput`.

It does **not** perform query validation, retrieval, fusion, reranking, adaptive top-K selection, candidate deduplication, semantic claim-to-source verification, source URL generation, document authorization, document opening, or end-to-end orchestration. Request-scoped citation-ID existence checking is implemented through `app.validation`; semantic support verification remains outside this module.

## 26.3 Input contract

The public synchronous and asynchronous methods have the same inputs:

| Argument | Type | Meaning |
|---|---|---|
| `current_query` | `str` | Current user question |
| `retrieved_documents` | `Sequence[dict[str, Any]]` | Final ranked retrieval candidates, normally the retrieval service's `selected_candidates` |
| `conversation_history` | `Sequence[BaseMessage] \| None` | Optional chronological LangChain messages; defaults to no history |

Conversation history is optional. The implementation passes the supplied messages to a LangChain `MessagesPlaceholder`; it does not rewrite or reorder the sequence. The intended conversation content is Human/AI messages.

### Retrieval candidate shape

The retrieval service returns a dictionary whose `selected_candidates` value is a list of candidate dictionaries. The generation code consumes these candidate fields:

- `page_content`: retrieved chunk text; required to produce a usable evidence item.
- `metadata`: optional descriptive metadata dictionary.

The retrieval candidates may also contain internal fields such as `chunk_id`, `global_rank`, `global_rrf_score`, `reranker_score`, and `provenance`. The current generation prompt preparation does not use those fields.

A typical call is:

```python
result = generation_agent.generate(
    current_query="What is the annual leave entitlement?",
    retrieved_documents=retrieval_result["selected_candidates"],
    conversation_history=history,  # optional
)
```

The retrieval service is an upstream dependency; the Generation Agent does not call it.

## 26.4 Evidence preparation

`GenerationAgent._prepare_evidence()` preserves the incoming candidate order and constructs a reduced evidence list.

For each candidate with non-empty string `page_content`, it creates:

| Prompt field | Source |
|---|---|
| `evidence_id` | Generated sequentially as `E1`, `E2`, ... |
| `content` | Trimmed `page_content` |
| `document` | First available of `metadata.document_title`, `metadata.source_filename`, or `metadata.source` |
| `page` | `metadata.page`, when present |
| `section` | First available of `metadata.section_heading` or `metadata.section` |

Candidates with missing, non-string, or blank chunk text are skipped. A candidate that is not a dictionary raises `TypeError`. Non-empty metadata values must be dictionaries.

The prompt deliberately excludes backend identifiers, storage locations, authorization details, retrieval scores, and embeddings. This keeps the model-facing context limited to chunk content and selected descriptive metadata. The full candidate objects are not modified.

Evidence IDs are local to a generation request. They are not database identifiers and are not canonical document references.

## 26.5 Prompt construction and grounding policy

`prompts.py` builds a `ChatPromptTemplate` with these messages, in order:

1. System instructions and structured-output format instructions.
2. Optional conversation history through `MessagesPlaceholder`.
3. A human message containing JSON-encoded current query and JSON-encoded retrieved evidence.

The system prompt establishes these rules:

- Company-related factual answers must be grounded in retrieved company-document evidence.
- The model must not use general knowledge or model memory to fill gaps in company facts.
- Conversation history can resolve references but is not authoritative evidence for company facts.
- The query, history, and retrieved text are untrusted data; instructions inside them must not override system rules.
- Unrelated evidence must not be treated as sufficient merely because the evidence list is non-empty.
- Unsupported claims and invented citations are prohibited.

The model is asked to choose one of three statuses:

- `answered`: evidence sufficiently supports the answer.
- `partial`: some relevant information is supported, but the evidence is incomplete.
- `insufficient_evidence`: the supplied evidence cannot support an answer.

Factual claims are associated with evidence IDs at the answer-segment level. The prompt forbids generating URLs, storage paths, document IDs, or page references as citation destinations.

## 26.6 Output schema

The Pydantic models in `schemas.py` define the response contract.

`GenerationStatus` is a string enum with values:

- `answered`
- `partial`
- `insufficient_evidence`

`AnswerSegment` contains:

- `text: str` — non-empty answer text.
- `citations: list[str]` — evidence IDs supporting claims in that segment; defaults to an empty list.

`GenerationOutput` contains:

- `status: GenerationStatus`
- `segments: list[AnswerSegment]` — at least one ordered segment.

Both Pydantic models reject extra fields and strip surrounding whitespace from string values. The schema validates structure and types; it does not establish that a cited evidence ID exists or semantically supports the associated claim.

## 26.7 LLM client and configuration

`GenerationConfig` is a frozen, slotted dataclass:

| Setting | Default | Constraint |
|---|---:|---|
| `temperature` | `0.1` | Between 0 and 2 |
| `max_output_tokens` | `2000` | Positive integer; booleans are rejected |

`GeneratorLLMClient` creates a `ChatOpenAI` instance using the existing application settings:

- `settings.OPENAI_MODEL`
- `settings.OPENAI_BASE_URL`
- `settings.OPENAI_API_KEY`

The generation configuration supplies temperature and maximum output tokens. A module-level `generator_llm_client` instance is exported. The agent also accepts an injected model for testing or custom construction.

## 26.8 Execution flow

```text
Caller
  |
  | current_query
  | retrieved_documents (selected_candidates)
  | optional conversation_history
  v
GenerationAgent.generate() / agenerate()
  |
  v
_prepare_evidence()
  |
  +-- no usable evidence --> deterministic insufficient_evidence output
  |
  v
Build chain input
  |
  v
ChatPromptTemplate
  |
  v
ChatOpenAI model (one invocation)
  |
  v
PydanticOutputParser(GenerationOutput)
  |
  v
GenerationOutput
```

Both `generate()` and `agenerate()` use the same evidence preparation and response schema. The former calls `chain.invoke()`; the latter calls `chain.ainvoke()`.

If evidence preparation produces an empty list, the agent does not call the model. It returns a deterministic `insufficient_evidence` response with one explanatory segment and no citations. This shortcut applies when no usable chunk text remains; it does not assess relevance. When one or more chunks exist, relevance and sufficiency are left to the model's instructed evidence assessment.

## 26.9 Error and validation behavior

- A non-dictionary candidate raises `TypeError`.
- A non-empty invalid metadata value raises `TypeError`.
- Blank or non-string `page_content` is skipped.
- Model output is parsed by `PydanticOutputParser` into `GenerationOutput`.
- If a chain returns a value that is not already a `GenerationOutput`, the agent applies `GenerationOutput.model_validate()`.
- `GenerationAgentError` is defined and exported, but the current implementation does not explicitly wrap other exceptions in it.

The agent does not add a separate blank-query validation step. Citation IDs are checked against request evidence before sync, async, or streaming-completion results are returned.

## 26.10 Citation behavior and current limitations

The model returns evidence IDs such as `E1` in each segment's `citations` list. Before sync, async or streaming completion is returned, Generation Agent checks that each cited ID exists in the evidence prepared for this request. This is an existence check, not proof that the cited passage semantically supports the claim.

The Generation Agent now validates citation-ID existence against the evidence prepared for the current request. The separate `app.validation` package also provides post-generation schema checks, citation checks, status consistency checks, and allowlisted citation metadata mapping. The current code does **not**:

- verify that a cited chunk semantically supports its claim;
- map evidence IDs to canonical document/version records;
- create application document-viewer links;
- generate signed storage URLs;
- enforce document authorization when a citation is opened.

The broader post-generation validator requires the same ordered retrieval candidates used during generation, because evidence IDs are assigned in order after blank chunks are skipped. It returns trusted metadata for cited IDs but does not return viewer URLs. Do not treat an evidence ID as a canonical document identifier or as permission to open a document. See [Static validation and citation mapping](27-static-validation.md).

## 26.11 LangGraph workflow adapter

`app/workflows/rag/nodes/generation.py` exposes `create_generation_node(agent)`. The factory receives an application-configured `GenerationAgent` rather than constructing model dependencies inside the node. Its asynchronous node calls `agent.agenerate()` with:

- `state["query"]` as the original validated user query;
- `state.get("retrieved_documents") or []` as the accumulated retrieval candidates, preserving their existing order;
- `state.get("context")` as optional conversation history.

The node passes `context_documents` when the Context Compression node has populated that field; otherwise it falls back to `retrieved_documents`. It does not rerun retrieval or alter evidence ordering. The Static Validation adapter uses the same selected evidence view, preserving the request-scoped citation registry. The Context Compression node retains original retrieval candidates separately and only changes `page_content` in its one-to-one compressed view. Static Validation stores its `GenerationValidationResult` in `validation_result`.

## 26.12 Tests

`tests/agent/test_generation.py` covers:

- structured generation output;
- evidence ordering and selected descriptive metadata in the prompt;
- exclusion of internal IDs and retrieval scores from the prompt;
- preservation of supplied conversation history;
- deterministic no-evidence behavior without a model call;
- asynchronous generation;
- configuration validation;
- rejection of unknown output-schema fields.

The user ran `uv run pytest tests/agent/test_generation.py -v` on 4 November 2026 and reported **11 passed in 6.68 seconds**. The tests use injected `RunnableLambda` components rather than making live model calls.

## 26.13 Current implementation status

| Capability | Status |
|---|---|
| Dedicated Generation Agent package | Implemented |
| Sync and async generation methods | Implemented |
| Optional conversation history | Implemented |
| Retrieval `selected_candidates` input | Implemented |
| Prompt-safe evidence IDs and metadata | Implemented |
| Company-document grounding instructions | Implemented |
| Structured Pydantic response | Implemented |
| Deterministic response when no usable evidence exists | Implemented |
| Request-scoped citation-ID existence validation in Generation Agent | Implemented and focused-test-verified (11 tests) |
| Citation-to-document/source resolution | Not implemented |
| Authenticated document viewer/gateway | Not implemented |
| End-to-end AI orchestrator | Not implemented |
| Streaming generation | Implemented; final structured output follows citation-ID validation |



## LangGraph orchestration

The end-to-end workflow is assembled in `app/workflows/rag/graph.py`. The graph receives already-configured dependencies through `create_rag_graph(...)`; it does not instantiate duplicate agents or retrieval services during module import.

The workflow is:

1. Input Validation normalizes the query. Invalid input routes directly to END.
2. Retriever calls the existing RetrievalOrchestrator. The node accumulates unique evidence, tracks excluded chunk IDs, increments the retrieval-attempt count, and records per-attempt diagnostics.
3. Evidence Sufficiency Evaluator judges the accumulated evidence against the original query.
4. Insufficient evidence routes to Retrieval Expansion only while the total retrieval-attempt count is below the configured maximum (3 by default). Expansion returns retrieval guidance, then the same Retriever node runs again with chunk exclusions enabled.
5. When evidence is sufficient or the attempt limit is reached, the graph checks the accumulated document count. More than 15 documents routes through Context Compression; 15 or fewer bypass it.
6. Both paths converge on Generation and then Static Validation. The graph ends with the validation result in workflow state.

The retry limit is checked before Retrieval Expansion is invoked, so the third insufficient evaluation does not trigger an unnecessary expansion-model call. The original query remains unchanged throughout the loop.

### Workflow graph

```mermaid
flowchart TD
    START([START]) --> IV[Input Validator]
    IV --> VALID{Is query valid?}
    VALID -->|No| END([END])
    VALID -->|Yes| RET[Retriever]
    RET --> EVAL[Evidence Sufficiency Evaluator]
    EVAL --> SUFF{Evidence sufficient?}
    SUFF -->|No| LIMIT{Attempts < 3?}
    LIMIT -->|Yes| EXP[Retrieval Expansion Agent]
    EXP --> RET
    SUFF -->|Yes| COMP_FILTER{Accumulated documents > 15?}
    LIMIT -->|No| COMP_FILTER
    COMP_FILTER -->|Yes| COMP[Context Compression]
    COMP_FILTER -->|No| GEN[Generation Agent]
    COMP --> GEN
    GEN --> SV[Static Validation]
    SV --> END
```

### Graph configuration

`RAGWorkflowConfig` defines `max_retrieval_attempts=3` and `compression_document_threshold=15`. Both values are validated and can be overridden when constructing the graph.

## 26.14 End-to-end workflow smoke test

The live workflow smoke-test runner is `scripts/workflow_E2E.py`. It constructs the application dependencies and invokes the LangGraph workflow for three scenarios: a simple company-policy question without history, a follow-up with Human/AI conversation history, and a whitespace-heavy query.

A synthetic two-page employee leave policy PDF was ingested and indexed for the smoke test. The ingestion output reported nine Qdrant chunks and active indexing. Using the same organization/user identity returned by ingestion, the first two scenarios retrieved evidence, generated grounded answers, and passed Static Validation with citation metadata resolved.

A subsequent run with a different organization/user identity returned no evidence for the first two scenarios but did retrieve three documents for the third scenario, producing a qualified partial answer. This inconsistency remains an investigation item. It does not prove cross-tenant isolation and does not, by itself, prove a cross-tenant data leak. Inspect authorization catalogue scoping, document ownership/access metadata, and the actual Qdrant payload filters before drawing a security conclusion.

The script currently counts successful workflow completion and Static Validation, not full semantic answer correctness. A `3/3` script summary must not be interpreted as all three responses being fully answered or independently quality-reviewed.

Warnings observed during local runs included unauthenticated Hugging Face Hub requests and the deprecated `fitz` API. They did not stop the reported workflow run; the full test suite also reported a LangChain community-package deprecation warning.

## 26.15 Current workflow verification

The user reported `uv run pytest tests/workflows -v`: **45 passed in 29.84 seconds**, and `pytest -v`: **393 passed, 2 warnings in 163.43 seconds**. These are local user-reported results, not CI or production verification.