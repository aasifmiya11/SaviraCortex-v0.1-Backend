# SaviraCortex Retrieval Evaluation

## Directory layout

- `corpus/source_pdfs/`: original PDF files supplied for the evaluation corpus.
- `datasets/`: manually curated, versioned retrieval benchmark questions, reference contexts, relevant document/chunk IDs and relevance grades.
- `config/`: evaluation-only configuration and run manifests. Keep secrets out of version control.
- `scripts/`: orchestration that calls existing SaviraCortex services.
- `results/`: ingestion manifests, per-query retrieval outputs and raw metric results.
- `reports/`: aggregate comparisons, charts and final evaluation reports.

## Ingestion workflow

The evaluation runner reuses the application's existing document lifecycle:

1. `DocumentIngestionService.ingest_pdf(..., organization_id=...)` validates each PDF, extracts text with the configured native-first/OCR loader, normalizes content, summarizes it, checks duplicates, uploads the original to B2 and registers a pending version.
2. `DocumentIndexingOrchestrator.index_pending_version(..., organization_id=...)` downloads and verifies the original, runs the same configured PDF/OCR loader, chunks and embeds all extracted pages, writes chunk metadata to Qdrant, stores the summary and activates the version.
3. The runner records page counts, OCR page counts, chunk counts, document/version IDs and indexing lifecycle warnings in an ingestion manifest under `results/`.

No parallel PDF parser, OCR implementation, splitter, embedding implementation or Qdrant writer is introduced by the evaluation runner. The application services remain the source of truth.

## Required environment

Load the same application credentials/configuration used by SaviraCortex, then set these evaluation-only variables in `.env` or the process environment:

```dotenv
SAVIRACORTEX_EVAL_ORGANIZATION_ID=3976ac6b-fd4e-4b44-beda-6c516b45a245
SAVIRACORTEX_EVAL_QDRANT_COLLECTION=saviracortex_eval_chunks
SAVIRACORTEX_EVAL_QDRANT_SUMMARY_COLLECTION=saviracortex_eval_summaries
SAVIRACORTEX_EVAL_B2_STORAGE_PREFIX=voice-ai/evaluation/
```

The organization UUID above is a proposed ID for the dedicated evaluation organization. It must first be inserted as a row in the database's `organizations` table (with a name such as `SaviraCortex Evaluation`). Setting the environment variable does not create the organization record. Do not use this ID until that row exists.

These variables are exposed through `app/core/config.py` as `settings.EVAL_ORGANIZATION_ID`, `settings.EVAL_QDRANT_COLLECTION_NAME`, `settings.EVAL_QDRANT_SUMMARY_COLLECTION_NAME` and `settings.EVAL_B2_STORAGE_PREFIX`.

The runner overrides the application's `QDRANT_COLLECTION_NAME`, `QDRANT_SUMMARY_COLLECTION_NAME` and `B2_STORAGE_PREFIX` before importing app services, because those services initialize storage/vector-store singletons during import. It refuses to run if an evaluation resource name/prefix is identical to the configured production/default value.

Organization-scoped ingestion does not require a user ID. Organization membership, user assignment and ACL setup are separate database administration tasks and are not performed by this script.

## Run

From the repository root:

```powershell
uv run python evaluation/scripts/ingest_corpus.py
```

Or provide the organization explicitly:

```powershell
uv run python evaluation/scripts/ingest_corpus.py --organization-id 3976ac6b-fd4e-4b44-beda-6c516b45a245
```

The resume PDF is excluded by default, consistent with the benchmark corpus decision. To include it deliberately, pass `--allow-resume`.

The runner stops after a hard failure and writes an incremental JSON manifest to `evaluation/results/ingestion_<run-id>.json`. A duplicate is recorded and skipped; a possible duplicate requiring manual review is recorded and results in exit code 2. A successful new ingestion is indexed and activated before the runner proceeds.

**Do not run against production resources.** Benchmark questions and relevance judgments will be curated separately and must not be placed in the PDF ingestion folder or indexed in Qdrant.
