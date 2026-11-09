# RAG feedback dataset

SaviraCortex stores each successfully validated generation in PostgreSQL in the
generation_feedback table. This is the source dataset for later retrieval and answer
evaluation.

Each row contains:

- query: the original user question.
- generated_queries and generated_query_count: the multi-query generator output
  as an ordered JSON list and its count.
- retrieval_trace: retrieval settings, query branches, candidate-version IDs,
  branch/rank diagnostics, fusion/reranking/selection counts, and single-pass
  retrieval diagnostics.
- retrieved_documents: the exact selected chunks passed to the generation model,
  including their text, document/version metadata, chunk IDs, scores, and provenance.
- answer_markdown and answer_status: the final citation-validated Markdown answer
  and generation status.
- feedback_status: relevant, not_relevant, or NULL until a person labels it.
- organization/user IDs and timestamps.

The chat response includes generation_id. The chat UI sends a relevance label to:

PATCH /api/v1/organizations/{organization_id}/generation/{generation_id}/feedback

Request body:

    {"feedback_status": "relevant"}

Use not_relevant for a thumbs-down. The database stores semantic labels, not UI
emoji values. A later vote updates the same row.

To retrieve the labeled evaluation set:

GET /api/v1/organizations/{organization_id}/generation/feedback-dataset

The endpoint returns labeled rows by default. Use labeled_only=false to include
unlabeled examples, or feedback_status=relevant / feedback_status=not_relevant
to select one class. Results are paginated with limit and offset. Owners and admins can export all
organization examples; regular members can label and export only their own rows.

For a fresh database, run python -m scripts.init_database from the backend directory to create all SQLAlchemy model tables, including generation_feedback. The generation service also performs a check-first table creation on the first successful generation save, so the database role needs table-creation permission if that table has not already been created.
