# 10. AI Agents and LLM Workflows

Three LLM workflows are present under `app/agents/`. They are not architecturally identical: the multi-query generator uses LangGraph, while the document summarizer and Generation Agent are direct prompt/model/parser chains.

## Document summarizer

`app/agents/Document_summarizer/agent.py` implements a stateless `DocumentSummarizerAgent`. It accepts sampled LangChain `Document` pages, rejects empty input, combines non-empty page text into a prompt, invokes a structured-output chain, and returns a validated `DocumentSummarizerOutput`.

The output schema requires four string fields: `title`, `document_type`, `description`, and `summary`; extra fields are forbidden and strings are stripped. The default configuration is a 500-character summary target, descriptive/technical style, English, temperature 0.2, and 2,000 output tokens. The default path uses `SummarizerLLMClient` and a LangChain Pydantic output parser. An optional injected OpenAI-compatible client path parses JSON and validates it with the same Pydantic schema. This agent does not access PostgreSQL, Qdrant or file storage.

## Multi-query generator

`app/agents/Multi_query_generator/agent.py` implements `MultiQueryGeneratorAgent` as a one-node LangGraph (`START -> generate_queries -> END`). The node invokes a prompt/model/Pydantic parser chain. The agent supports synchronous `generate()` and asynchronous `agenerate()`, accepts conversation history and an `AvailableDocuments` catalogue, rejects empty queries, and returns at most six queries by default.

Each generated query has a text query, a version scope (`active`, `superseded`, or `both`), and optional target version years. Pydantic schemas reject extra fields, empty/duplicate query strings, invalid years, and inconsistent active/superseded catalogue entries. The agent additionally verifies that target years exist in the catalogue and belong to the declared scope.

## Generation agent

`app/agents/Generation/agent.py` implements a stateless company-grounded `GenerationAgent` as a direct LangChain prompt/model/Pydantic-parser chain. It accepts the current query, optional chronological LangChain conversation messages, and the retrieval service's final `selected_candidates` list. It preserves candidate order, skips candidates without usable text, assigns request-scoped evidence IDs (`E1`, `E2`, ...), and exposes only chunk text plus selected descriptive metadata to the prompt. Internal IDs, retrieval scores, storage details and permissions are excluded.

The prompt treats retrieved company evidence as the factual basis for company-specific answers. Conversation history may resolve references but is not authoritative evidence. The output uses `GenerationStatus` (`answered`, `partial`, or `insufficient_evidence`) and ordered `AnswerSegment` objects containing text and evidence-ID citations. Both synchronous `generate()` and asynchronous `agenerate()` are available. If no usable evidence remains after preparation, the agent returns a deterministic insufficient-evidence response without invoking the model.

`GenerationConfig` defaults to temperature 0.1 and 2,000 output tokens. `GeneratorLLMClient` uses the existing `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_API_KEY` settings. The agent delegates request-scoped citation-ID existence checks to `app.validation`. The separate Static Validation Layer can validate a complete output and map cited IDs to allowlisted document/version/page metadata when given the original ordered retrieval candidates. Neither component performs semantic claim-to-source verification, resolves viewer URLs, opens documents, or orchestrates other components. See [Generation pipeline](26-generation-pipeline.md) and [Static validation](27-static-validation.md).

## LLM client defaults

| Client | Temperature | Output token default |
|---|---:|---:|
| Summarizer | 0.2 | 2000 |
| Multi-query | 0.2 | 1500 |
| Retrieval | 0.0 | 1500 |
| Generator | 0.1 | 2000 |
| General `LLMClient` | Provider default | Not set here |

All specialized clients use `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_API_KEY`. Structured validation constrains output shape but cannot guarantee semantic correctness. Document content is sent to the configured model provider when these workflows run; assess provider privacy and retention settings accordingly.
