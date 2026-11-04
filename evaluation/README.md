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


## Production retrieval execution and rank capture

The retrieval measurement runner uses the application's existing
RetrievalOrchestrator; it does not implement a second retrieval algorithm.
It loads the frozen question dataset and passes each question's text as
current_query and its role-based conversation history as LangChain
HumanMessage/AIMessage objects.

The runner applies two boundaries before retrieval:

1. It switches the application Qdrant chunk and summary collection settings to
   the two evaluation collections before importing modules that initialize
   Qdrant singletons. It performs a read-only preflight and refuses to run if
   either collection is missing or the chunk count differs from the 485-point
   corpus lock.
2. It uses the application's PostgreSQL AuthorizationRepository and
   AuthorizationService for the evaluation organization/user, then narrows
   the authorized catalogue to the seven document versions in
   corpus_lock.json. Every locked version must be authorized. A fresh
   database session is used for each question.

The production orchestration path remains:

~~~text
conversation + current question
  → multi-query agent
  → authorized document summary candidates
  → local hybrid retrieval
  → global RRF fusion
  → cross-encoder reranking
  → adaptive-K selection
~~~

Evaluation-only recording adapters delegate to the actual hybrid pipeline and
cross-encoder reranker and return their results unchanged. They capture
intermediate results that the public orchestrator response does not expose.

Run one question first:

~~~powershell
uv run python evaluation/scripts/run_retrieval_evaluation.py --limit 1
~~~

Run all 293 generated question variants after the smoke test:

~~~powershell
uv run python evaluation/scripts/run_retrieval_evaluation.py
~~~

Useful controls include --offset, --limit, --top-k, --candidate-k,
--mode hybrid|bm25|dense, --score-threshold, --k-min, --k-max, and
--max-expansion-rounds. Defaults are top_k=10, candidate_k=20, mode=hybrid,
rrf_k=60, adaptive k_min=3, k_max=10, score threshold 0.6, and at most two
expansion rounds.

Each run writes a JSON Lines file under evaluation/results/. It is
incremental: each question result is flushed as soon as it finishes. The file
contains a run manifest, one result record per question, and a final run
summary. Each successful question record preserves:

- Original question text and conversation context.
- Queries generated by the production multi-query agent.
- Summary-based document candidates for each query-generation pass, including
  version scope, candidate document/version IDs, and summary similarity scores.
- Per-query local hybrid retrieval results, with retrieval rank and score.
- Global fused candidates, with global RRF rank and score.
- The complete final cross-encoder reranked candidate list, with explicit
  reranked_rank and reranker_score.
- Final adaptive-K selected candidates, with explicit selected_rank.
- Chunk text, source filename, page, document/version metadata, stable
  document_version_id:chunk_index chunk identity, Qdrant point UUID, and
  query-branch provenance.
- Expansion rounds, branch statistics, and selection counts.

The stable chunk_id used for qrels is the same
document_version_id:chunk_index identity used by global fusion and the
verified chunk catalogue. The original Qdrant point UUID is also recorded for
traceability. The curated retrieved_chunks attached to a generated question
are **not** passed into the production retriever and are not used as relevance
labels.

This runner does not ingest, update, or delete Qdrant points. It does not
modify application code. The normal application Qdrant client may ensure
payload indexes during initialization; the evaluation collections already
have the indexes required by the frozen corpus.

## Relevance judgments and metric scoring

Retrieval output alone is not enough to calculate valid Recall or nDCG.
For the current partial Hybrid run, prepare a blank human-review file from
only its successful question records:

~~~powershell
uv run python evaluation/scripts/prepare_run_relevance_judgments.py --run evaluation/results/hybrid_parallel_293.jsonl --output evaluation/datasets/relevance_judgments_hybrid_successful.json
~~~

This run-specific file excludes failed retrieval records, includes only
successful question IDs, and does not assign relevance labels. The generic
`prepare_relevance_judgments.py` script still creates a template for the
entire question dataset; do not use that generic template for this partial-run
scoring workflow.

For each question:

1. Set question_approved=true after reviewing the question and its context.
2. Screen **all 485 chunks** in the frozen corpus independently of the
   retrieval results. Add every relevant chunk to relevant_chunks using
   its catalogue chunk_id and a relevance grade: 1 (marginal/supporting),
   2 (relevant evidence), or 3 (highly relevant/direct evidence).
3. Do not add non-relevant chunks; their absence means grade 0 after the
   complete screening has been performed.
4. Set judgment_complete=true only after all 485 chunks have been screened.
   Record the reviewer and any notes.
5. Set the top-level judgment_status to in_review while a subset of
   questions has complete judgments, or complete when the full dataset is
   finished.

The scorer rejects unapproved questions, incomplete corpus screening, chunk IDs
outside the locked catalogue, duplicate labels, and questions with no positive
relevance labels. A partial qrels file can score a small retrieval run if every
question in that run has completed judgments; unfinished qrels for unrelated
questions are skipped.

Score a captured run:

~~~powershell
uv run python evaluation/scripts/score_retrieval_results.py --run evaluation/results/retrieval_run_<run-id>.jsonl --qrels evaluation/datasets/relevance_judgments_20261104.json
~~~

The scorer calculates macro-averaged Precision@K, Recall@K, MRR@K and graded
nDCG@K at K = 1, 3, 5 and 10 by default. It reports two ranking views:

- full_reranked_list: the complete cross-encoder ranking before adaptive
  score-threshold filtering.
- adaptive_selected_list: the final list returned by the production
  adaptive-K selector.

Precision uses K as its denominator; if fewer than K chunks are returned,
missing positions count as non-relevant. Recall uses every independently
judged relevant chunk as its denominator. nDCG uses gains
2^relevance_grade - 1. Aggregate metrics are macro-averaged across questions.
Reports are written to evaluation/reports/.

Question review and relevance review are separate gates. The current
generated-question dataset is still marked pending_human_review; retrieval
runs can be used for exploratory inspection, but metric reports are benchmark
results only after the corresponding questions are approved and their
whole-corpus relevance judgments are complete. Reference answers are not
required for these chunk-ranking metrics; they are a separate requirement for
answer-quality evaluation.


Before the first retrieval run, ensure the evaluation database identity exists
and has the expected organization membership. First preview the database
changes:

~~~powershell
uv run python evaluation/scripts/setup_evaluation_identity.py
~~~

Review the printed organization, user and membership actions. Only if the
preview is correct, commit the evaluation identity setup:

~~~powershell
uv run python evaluation/scripts/setup_evaluation_identity.py --apply
~~~

This uses the evaluation organization ID from the environment/corpus lock and
creates or reuses its database-only service user and admin membership. It does
not create a Firebase login. The retrieval runner then checks that this
identity is authorized for all seven locked document versions. The Qdrant
preflight also requires the evaluation summary collection to contain seven
points and the chunk collection to contain 485 points.


## Comparing retrieval configurations

To compare the local retrieval modes, run the same question slice with the same
top_k, candidate_k, RRF, adaptive-K and reranker settings. Change only the
local retrieval mode:

~~~powershell
uv run python evaluation/scripts/run_retrieval_evaluation.py --mode hybrid --output evaluation/results/hybrid.jsonl
uv run python evaluation/scripts/run_retrieval_evaluation.py --mode bm25 --output evaluation/results/bm25.jsonl
uv run python evaluation/scripts/run_retrieval_evaluation.py --mode dense --output evaluation/results/dense.jsonl
~~~

The selected mode controls the local per-query retriever. The orchestrator
still performs its multi-query generation, cross-query global fusion,
cross-encoder reranking and adaptive selection in each run.

Compare the runs against the same completed qrels:

~~~powershell
uv run python evaluation/scripts/score_retrieval_results.py --run evaluation/results/hybrid.jsonl evaluation/results/bm25.jsonl evaluation/results/dense.jsonl --qrels evaluation/datasets/relevance_judgments_20261104.json
~~~

The first run supplied to --run is the baseline. The comparison report includes
each run's macro-averaged metrics and metric deltas against that baseline.
All runs are scored on the intersection of successfully completed question IDs,
so a partial run cannot silently be compared on a different query population.
For a fair comparison, use identical question IDs and retrieval settings except
for the single configuration dimension being tested.


Validate the question/corpus inputs without connecting to PostgreSQL, Qdrant,
the LLM provider, or the cross-encoder:

~~~powershell
uv run python evaluation/scripts/run_retrieval_evaluation.py --validate-only
~~~


## Parallel retrieval workers

For faster full-corpus question runs, use the evaluation-only worker launcher.
It starts 2 or 3 independent Python processes; each process initializes its own
retrieval orchestrator, model clients and recording adapters, and processes a
separate contiguous slice of the same frozen question dataset. This avoids
sharing the runner's per-question capture buffers between concurrent tasks.

Start with two workers:

~~~powershell
uv run python evaluation/scripts/run_retrieval_workers.py --workers 2 --mode hybrid --output evaluation/results/hybrid_parallel_293.jsonl
~~~

Use three only if the machine has enough memory and the model provider/Qdrant
service can handle the additional simultaneous load:

~~~powershell
uv run python evaluation/scripts/run_retrieval_workers.py --workers 3 --mode hybrid --output evaluation/results/hybrid_parallel_293_3workers.jsonl
~~~

The launcher retains each worker's standalone JSONL trace beside the combined
JSONL output. The combined file contains one manifest, all question results in
the original dataset order, and one aggregate summary. Do not run two launchers
against the same output name. Worker processes increase simultaneous database,
Qdrant, embedding, reranker and LLM activity; they may improve throughput but
can also increase memory use, provider throttling, or transient service errors.
The existing `--retrieval-concurrency` setting remains the per-question branch
concurrency and is separate from `--workers`. Start with 2 workers and compare
elapsed time and failure counts before increasing to 3.

The launcher and its outputs are evaluation-only. It does not change production
application code or write/delete Qdrant points.


## Scoring a partial retrieval run

A retrieval run does not need to succeed for all 293 generated questions.
For this benchmark, failed retrieval records are excluded from the scoring
population. The following script creates a blank qrels file containing only
question IDs whose status is `succeeded` in the chosen JSONL run. It verifies
the source dataset and run against the frozen corpus lock and chunk catalogue.
Failed question IDs are counted in the qrels metadata but are not included as
judgment records.

Prepare qrels for the successful questions in the existing Hybrid run:

~~~powershell
uv run python evaluation/scripts/prepare_run_relevance_judgments.py --run evaluation/results/hybrid_parallel_293.jsonl --output evaluation/datasets/relevance_judgments_hybrid_successful.json
~~~

The script does not copy relevance grades from the run or from the question's
seed evidence. For every included question, review the question/context,
approve it, screen all 485 frozen corpus chunks independently, and add every
relevant chunk with grade 1, 2 or 3. Seed evidence IDs are navigation hints
only. Keep the top-level judgment_status as `in_review` while reviewing.

Score the Hybrid run's successful questions after all included judgments are
complete:

~~~powershell
uv run python evaluation/scripts/score_retrieval_results.py --run evaluation/results/hybrid_parallel_293.jsonl --qrels evaluation/datasets/relevance_judgments_hybrid_successful.json --allow-partial
~~~

The `--allow-partial` flag explicitly permits failed retrieval records to be
ignored. The scorer evaluates only successful question IDs and requires
completed relevance judgments for each of them. It calculates macro-averaged
Precision@K, Recall@K, MRR@K and graded nDCG@K at K=1,3,5,10 for both the
full reranked list and final adaptive-selected list. The scorer streams each
JSONL file and retains only ranked chunk IDs needed for metric calculation;
large chunk text, branch traces and other diagnostics are discarded during
scoring to reduce memory use.

For comparisons, supply two or more run files. The scorer intersects their
successful question IDs and evaluates every run on that same intersection.
Every question in that common set must have completed qrels. For example:

~~~powershell
uv run python evaluation/scripts/score_retrieval_results.py --run evaluation/results/hybrid_parallel_293.jsonl evaluation/results/bm25_full_293.jsonl --qrels evaluation/datasets/relevance_judgments_hybrid_successful.json --allow-partial
~~~

This example compares only the successful IDs common to both files; use the
Dense run path as an additional `--run` argument when it is available. The
first run is the baseline for reported metric deltas. No failed question needs
to be retried or investigated for this evaluation plan.
