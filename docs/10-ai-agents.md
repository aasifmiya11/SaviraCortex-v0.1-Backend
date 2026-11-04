# 10. AI Agents and LLM Workflows

Two LLM workflows are present under `app/agents/`. They are not architecturally identical: the multi-query generator uses LangGraph, while the document summarizer is a direct prompt/model/parser chain.

## Document summarizer

`app/agents/Document_summarizer/agent.py` implements a stateless `DocumentSummarizerAgent`. It accepts sampled LangChain `Document` pages, rejects empty input, combines non-empty page text into a prompt, invokes a structured-output chain, and returns a validated `DocumentSummarizerOutput`.

The output schema requires four string fields: `title`, `document_type`, `description`, and `summary`; extra fields are forbidden and strings are stripped. The default configuration is a 500-character summary target, descriptive/technical style, English, temperature 0.2, and 2,000 output tokens. The default path uses `SummarizerLLMClient` and a LangChain Pydantic output parser. An optional injected OpenAI-compatible client path parses JSON and validates it with the same Pydantic schema. This agent does not access PostgreSQL, Qdrant or file storage.

## Multi-query generator

`app/agents/Multi_query_generator/agent.py` implements `MultiQueryGeneratorAgent` as a one-node LangGraph (`START -> generate_queries -> END`). The node invokes a prompt/model/Pydantic parser chain. The agent supports synchronous `generate()` and asynchronous `agenerate()`, accepts conversation history and an `AvailableDocuments` catalogue, rejects empty queries, and returns at most six queries by default.

Each generated query has a text query, a version scope (`active`, `superseded`, or `both`), and optional target version years. Pydantic schemas reject extra fields, empty/duplicate query strings, invalid years, and inconsistent active/superseded catalogue entries. The agent additionally verifies that target years exist in the catalogue and belong to the declared scope.

## LLM client defaults

| Client | Temperature | Output token default |
|---|---:|---:|
| Summarizer | 0.2 | 2000 |
| Multi-query | 0.2 | 1500 |
| Retrieval | 0.0 | 1500 |
| General `LLMClient` | Provider default | Not set here |

All specialized clients use `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_API_KEY`. Structured validation constrains output shape but cannot guarantee semantic correctness. Document content is sent to the configured model provider when these workflows run; assess provider privacy and retention settings accordingly.
