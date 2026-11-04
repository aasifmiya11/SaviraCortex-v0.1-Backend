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

The organization UUID above is the dedicated evaluation organization recorded in the verified corpus lock. The organization record and evaluation collection must exist before running evaluation scripts. Keep this ID aligned with `evaluation/datasets/corpus_lock.json`; changing the organization requires a new corpus snapshot and verification.

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

## Synthetic Layer 1 query candidates

The candidate generator reads the live Qdrant payloads but first verifies them against the frozen corpus lock and full-text chunk catalogue. It stops if the organization, collection, point IDs, chunk identities, or chunk text differ from the locked 485-point corpus.

Run from the repository root:

```powershell
uv run python evaluation/scripts/generate_synthetic_dataset.py
```

The script uses `OPENAI_API_KEY`, `OPENAI_MODEL`, and optional `OPENAI_BASE_URL` from the application environment. It makes one model request for each proposed query category and writes a timestamped file under `evaluation/datasets/`. The proposed distribution totals 100 candidates: 20 direct factual, 20 semantic/conceptual, 15 multi-hop, 15 entity/relationship, 10 keyword-sensitive, 10 ambiguous/paraphrased, and 10 complex multi-document.

These counts are a proposed distribution and remain subject to corpus suitability review. Model output is candidate material only: `ground_truth` and `reference_answer` remain null, candidate source passages have no relevance grade, and every candidate is marked pending human review. Do not use the generated candidates as benchmark ground truth until reviewers verify the question and independently judge all relevant chunks.

The generator does not use RAGAS and does not modify Qdrant or application code. It only reads the locked corpus and writes a candidate JSON file.


## Structured question-variant generation

The evidence-group question generator is separate from the production retrieval
pipeline. It reads the 100 evidence-group candidates from
`datasets/evidence_group_candidates_20261104.json`, resolves their chunk IDs
against the verified full-text `datasets/chunk_catalogue.json`, and passes each
candidate's conversation context plus full evidence chunk text to one reusable
`ChatOpenAI` client.

The agent follows the same structure as the application agents:
`config.py` defines a frozen dataclass configuration, `schemas.py` defines
strict Pydantic output models, `prompts.py` builds a LangChain
`PromptTemplate` with `PydanticOutputParser` format instructions, and
`question_generation_agent.py` composes the pipeline as
`prompt | model | parser`. It obtains the model from the shared
`app.llm.client.llm_client` factory and constructs one agent for the full run.

The model chooses to return one, two or three distinct question variants.
Each variant is tagged as `context_dependent`, `balanced` or
`self_contained`, with an explicit context-dependency label. A successful run
therefore produces between 100 and 300 questions for the 100 candidates.

Run input validation without making an LLM call:

```powershell
uv run python evaluation/scripts/generate_evaluation_questions.py --validate-only
```

Run the complete generation:

```powershell
uv run python evaluation/scripts/generate_evaluation_questions.py
```

For a small live smoke test, process only the first candidate:

```powershell
uv run python evaluation/scripts/generate_evaluation_questions.py --limit 1
```

The script uses `OPENAI_API_KEY`, `OPENAI_MODEL` and optional
`OPENAI_BASE_URL` from the project environment. It writes a new timestamped
file named `generated_questions_<run-id>.json` under `evaluation/datasets/`.
Existing output files are not overwritten unless an explicit output path and
`--overwrite` are supplied. Failed candidate calls are recorded in the output;
an incomplete run exits with status 2.

Each question record contains a stable `question_id`, a nested `question`
object, the original role-based `context`, the full `retrieved_chunks` text and
metadata, and candidate/evidence provenance. In this generation stage,
`retrieved_chunks` means the curated evidence chunks supplied to the agent; it
does **not** mean chunks returned by the production retriever.

This stage generates questions only. It does not generate reference answers,
assign exhaustive relevance grades, call Qdrant, invoke the production retriever,
or modify application code or stored vectors. Every generated question remains
pending human review. The later benchmark-building stage must add reviewed
reference answers and independently judged relevant chunk IDs before metrics
such as Recall@K can be treated as definitive.
