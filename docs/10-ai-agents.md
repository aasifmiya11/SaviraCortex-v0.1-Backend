# 10. AI Agents

Two LangGraph agent packages are present: `app/agents/Document_summarizer/` and `app/agents/Multi_query_generator/`. Both separate agent code, configuration, prompts and Pydantic schemas.

## Document summarizer

Used during ingestion to infer document metadata from sampled normalized pages. Test fixtures show `title`, `document_type`, `description` and `summary` fields. It uses `SummarizerLLMClient`, configured from common model settings, with defaults of temperature 0.2 and 2000 output tokens. The source read for this agent implementation was blocked during this pass, so exact graph nodes, retries and internal validation are not asserted.

## Multi-query generator

`MultiQueryGeneratorAgent` constructs a LangGraph with one generation node between START and END. It rejects empty queries, accepts conversation history and an `AvailableDocuments` catalogue, invokes a prompt/model/Pydantic parser chain, truncates output to configured `max_queries`, and validates version targets against the catalogue. It supports `generate()` and `agenerate()`.

Generated queries may target active, superseded or combined scope. Active scope must target active version years; superseded scope must target superseded years; combined scope may target either available group. Unavailable years and scope/year mismatches raise agent errors.

## LLM client defaults

| Client | Temperature | Output token default |
|---|---:|---:|
| Summarizer | 0.2 | 2000 |
| Multi-query | 0.2 | 1500 |
| Retrieval | 0.0 | 1500 |
| General | Provider default | Not set here |

Structured validation reduces format/scope errors but cannot guarantee semantic correctness. Track model and prompt revisions, and ensure document content may be sent to the configured model provider.