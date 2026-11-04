# 29. Context Compression

## Purpose

The Context Compression Agent reduces the prompt footprint of accumulated retrieval evidence. It is a query-aware, one-to-one transformation: it does not merge chunks, drop chunks, or change their order.

## Package structure

- `app/agents/Context_compression/`: agent, configuration, prompt, and Pydantic output schema.
- `app/llm/context_compression_client.py`: dedicated model client using the existing OpenAI settings.
- `app/workflows/rag/nodes/context_compression.py`: injected LangGraph adapter.
- `tests/agent/test_context_compression.py` and `tests/workflows/test_context_compression.py`: focused tests.

## Input and output contract

The agent receives the original user query and the complete ordered list of accumulated retrieval candidates. It sends all candidate contents in one structured model request, each paired with a one-based input index.

The model must return exactly one compressed passage for every input index. The agent rejects missing, duplicate, additional, or reordered indexes. It copies each original candidate dictionary and changes only `page_content`. Metadata, stable chunk IDs, other retrieval fields, candidate count, and order are retained. Original candidate dictionaries are never mutated.

The model receives document content and indexes only. Backend metadata, internal IDs, retrieval scores, storage locations, and authorization information are not sent to the compression prompt.

## Conditional activation

The LangGraph workflow uses a document-count filter with a default threshold of 15 accumulated unique retrieved documents:

- 15 documents or fewer: skip the Context Compression Agent and proceed directly to Generation.
- More than 15 documents: invoke the Context Compression Agent, then proceed to Generation.

The count is evaluated after the retrieval loop has finished and uses the accumulated evidence across all retrieval attempts. This is a workflow routing decision intended to avoid an unnecessary model call and its associated cost.

When compression is invoked, the node estimates the input token count for diagnostics and compresses all documents. The previous token-threshold check is not used as a second gate. The agent retains its character-based token estimation helper, but it does not decide whether the graph invokes compression.

The original `retrieved_documents` remains unchanged and available for provenance. The compressed one-to-one view is stored in `context_documents`. Generation and Static Validation use `context_documents` when present, ensuring they see the exact same ordered evidence view. When compression is skipped, those nodes fall back to `retrieved_documents`.

## Information preservation requirements

The prompt instructs the model to preserve query-relevant facts, exact figures, dates, names, units, policy limits, conditions, exceptions, qualifications, negations, and historical/version distinctions. It must not add external facts or follow instructions embedded in source documents. Each output remains associated with its original candidate; request-scoped citation IDs therefore continue to resolve through the same ordered metadata registry.

## Current limitations

- The token estimate is character-based and diagnostic, not provider token accounting.
- Compression quality depends on the configured model and prompt; structured output and index checks guarantee shape and mapping, not semantic losslessness.
- The graph is dependency-injected; the application composition layer must provide configured agent and retrieval instances.
