# 16. Candidate Document Generation

Candidate generation narrows chunk retrieval to document versions that are both authorized and relevant at the summary level. It is implemented in `app/rag/retrieval/candidate_document_generator.py`.

## Inputs and authority

The generator receives generated queries, an authorized version catalogue obtained from PostgreSQL, and an organization ID. The catalogue must contain document/version IDs, title, summary, version year and lifecycle status. PostgreSQL remains authoritative for authorization, lifecycle and candidate metadata; Qdrant similarity scores are used only for ranking.

## Search process

For each generated query, the generator:

1. Filters the authorized catalogue by the query's `active`, `superseded`, or `both` version scope and optional target years.
2. Pushes the exact eligible version-ID allowlist and organization ID into the Qdrant summary search before top-K truncation.
3. Pages through summary results while searching for enough eligible candidates, subject to a maximum search budget.
4. Applies the similarity threshold and validates each hit's version and document IDs against the authoritative catalogue.
5. Uses catalogue title, summary, year and status rather than trusting those fields from Qdrant payloads.
6. Deduplicates versions within a query, keeps the highest similarity score, and returns up to the configured target candidate count. Duplicates across different queries are retained for later global fusion.

Default generator settings are similarity threshold `0.40`, page/search limit `20`, maximum search limit `200`, target candidate count `20`, and concurrency `6`.

## Failure semantics

A successful search with no matches returns an empty candidate list. A failed summary search is recorded separately. If every query's summary search fails, `CandidateDocumentGenerationError` is raised; partial query failures can be returned alongside successful results. The retrieval orchestrator converts initial candidate-generation failure into an empty structured response and records the error.

## Safety property

Candidate generation is not an authorization engine. It must consume the already-authorized catalogue and must never widen beyond its exact version allowlist. Missing or invalid catalogue data must not trigger an unrestricted vector search.

## Tests

See `tests/rag/retrieval/test_candidate_document_generator.py` and `test_candidate_scoped_retrieval.py`.
