# 16. Candidate Document Generation

Candidate generation narrows the search space before chunk retrieval. It is implemented in `app/rag/retrieval/candidate_document_generator.py` and receives a generated query plus the authorized/available document catalogue.

## Purpose

- Constrain search to documents the caller is allowed to access.
- Preserve version scope (active, superseded or combined).
- Reduce unnecessary vector search across unrelated documents.
- Provide document/version filters to dense and lexical retrieval.

## Inputs and constraints

The upstream multi-query agent validates version targets against available active/superseded versions. Candidate generation then uses the catalogue and query intent to create a bounded set of document/version candidates. The exact ranking heuristics and caps are implementation-defined; consult the module and its tests before tuning.

## Safety property

Candidate generation is a retrieval optimization, not an authorization engine. It must consume an already authorized catalogue and must not expand beyond it. Missing or invalid candidate scope should fail closed rather than search all tenant data.

## Tests

See `tests/rag/retrieval/test_candidate_document_generator.py` and `test_candidate_scoped_retrieval.py`.
