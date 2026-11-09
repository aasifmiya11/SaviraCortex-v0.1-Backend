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

The SQL migration is migrations/0001_generation_feedback.sql. Apply it to the
PostgreSQL database before deploying the updated backend, or run
python -m scripts.create_generation_feedback_table from the backend directory.
That command uses the configured backend PostgreSQL connection and creates only
this table if it is missing. The generation service also checks for the table on
its first save per database engine, so the database role needs table-creation
permission if the SQL migration has not already been applied.
