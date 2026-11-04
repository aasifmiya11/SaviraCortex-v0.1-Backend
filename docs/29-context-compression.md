# 29. Context Compression

## Purpose

The Context Compression Agent reduces the prompt footprint of accumulated retrieval evidence when its estimated size exceeds a configurable threshold. It is a query-aware, one-to-one transformation: it does not merge chunks, drop chunks, or change their order.

## Package structure

- `app/agents/Context_compression/`: agent, configuration, prompt, and Pydantic output schema.
- `app/llm/context_compression_client.py`: dedicated model client using the existing OpenAI settings.
- `app/workflows/rag/nodes/context_compression.py`: injected LangGraph adapter.
- `tests/agent/test_context_compression.py` and `tests/workflows/test_context_compression.py`: focused tests.

## Input and output contract

The agent receives the current user query and the complete ordered list of accumulated retrieval candidates. It sends all candidate contents in one structured model request, each paired with a one-based input index.

The model must return exactly one compressed passage for every input index. The agent rejects missing, duplicate, additional, or reordered indexes. It then copies each original candidate dictionary and changes only `page_content`. Metadata, stable chunk IDs, other retrieval fields, candidate count, and order are retained. Original candidate dictionaries are never mutated.

The model receives document content and indexes only. Backend metadata, internal IDs, retrieval scores, storage locations, and authorization information are not sent to the compression prompt.

## Conditional activation

The default configuration uses a 12,000-token threshold. The current implementation estimates tokens deterministically as:

`ceil((query characters + retrieved page-content characters) / chars_per_token)`

The default `chars_per_token` is 4. This is an approximate routing estimate, not provider token accounting. The threshold and estimator are configurable. At or below the threshold, the workflow node skips the model call and passes the original ordered candidates through as `context_documents`. Above the threshold, it stores the one-to-one compressed candidates in `context_documents`.

The original `retrieved_documents` remains unchanged and available to Retrieval Expansion. Evidence Evaluation, Generation, and Static Validation use `context_documents` when present, ensuring Generation and Static Validation see the exact same ordered evidence view. If compression has not run, those nodes fall back to `retrieved_documents`.

## Information preservation requirements

The prompt instructs the model to preserve query-relevant facts, exact figures, dates, names, units, policy limits, conditions, exceptions, qualifications, negations, and historical/version distinctions. It must not add external facts or follow instructions embedded in source documents. Each output remains associated with its original candidate; request-scoped citation IDs therefore continue to resolve through the same ordered metadata registry.

## Current limitations

- The token threshold uses a character-based estimate, not the model provider's tokenizer.
- Compression quality is dependent on the configured model and prompt; structured output and index checks guarantee shape and mapping, not semantic losslessness.
- The node is implemented and tested independently; end-to-end graph routing and composition remain a separate integration step.
