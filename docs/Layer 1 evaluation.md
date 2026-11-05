# Layer 1 Evaluation — Retrieval-Only Evaluation

**Project:** SaviraCortex  
**Status:** Scope agreed; frozen corpus verified; synthetic candidate generator implemented; benchmark review and evaluator implementation remain  
**Evaluation layer:** Layer 1 — retrieval pipeline  
**Document purpose:** Preserve the evaluation decisions and architecture so future work can continue from the same agreed plan.

---

## 1. Objective and scope

Layer 1 evaluates the quality of the SaviraCortex retrieval pipeline independently of answer generation.

The system under test receives a query and returns ranked chunks/documents. We evaluate whether the correct source material was retrieved, how completely it was retrieved, and how well it was ranked.

**No answer generator is required for Layer 1.** We do not generate an actual answer or require an expected/reference answer for the core retrieval metrics.

The benchmark must contain independently prepared relevance judgments. The retrieval results must never be used to create or determine the ground-truth labels.

### In scope

- Dense retrieval
- BM25 retrieval
- Hybrid retrieval
- Global fusion
- Cross-encoder reranking
- Full retrieval orchestration, including query expansion/multi-query and adaptive K
- Retrieval quality, context relevance, ranking quality, and retrieval performance
- Validation of the metric implementation itself

### Out of scope for Layer 1

- Answer generation
- Generated-answer correctness
- Answer faithfulness
- Answer relevancy
- Answer-versus-reference-answer scoring
- DeepEval answer-dependent contextual precision/recall
- LLM-based RAGAS metrics that require reference answers

These belong to Layer 2, after the generator pipeline exists.

---

## 2. Agreed metric inventory

### 2.1 Core information-retrieval metrics — implemented by SaviraCortex

These metrics are calculated directly from the ground-truth relevant chunk/document IDs and the actual ranked retrieval IDs. They do not require generated answers or an LLM judge.

| Metric | Meaning | Inputs |
|---|---|---|
| Recall@K | Fraction of all judged-relevant items retrieved within the first K results | Relevant IDs, retrieved ranked IDs |
| Precision@K | Fraction of the first K results that are judged relevant | Relevant IDs, retrieved ranked IDs |
| Hit Rate@K | Whether at least one relevant item appears within the first K results | Relevant IDs, retrieved ranked IDs |
| MRR@K | Reciprocal rank of the first relevant result, with zero if none is found in K | Relevant IDs, retrieved ranked IDs |
| NDCG@K | Ranking quality with position discounts and graded relevance | Ranked IDs, relevance grades |
| MAP@K | Mean/average precision over the ranked results, rewarding multiple relevant results appearing early | Relevant IDs, retrieved ranked IDs |

Calculate the ranking metrics at the following cutoffs:

- K = 1
- K = 3
- K = 5
- K = 10

Metric conventions must be documented and tested. In particular:
- Define whether Precision@K always divides by K or by the number of returned results when fewer than K are available. Choose one convention and apply it consistently; standard fixed-K Precision@K generally divides by K.
- Define MAP@K normalization consistently, including whether the denominator is the total number of relevant items or min(total relevant items, K). Record the convention in the evaluator.
- Use relevance grades for NDCG. Suggested grade scale: 0 = not relevant, 1 = marginally relevant, 2 = relevant, 3 = highly relevant.
- Hit Rate@K is a per-query binary measure; report its mean across queries.
- Report macro averages across queries. If useful, also report category-level averages.

### 2.2 Document-level and chunk-level retrieval measurements

Measure both document and chunk retrieval. Retrieving the correct document does not guarantee that the correct passage within that document was retrieved.

- Document Recall@K: proportion of relevant documents represented in the retrieved top K.
- Chunk Recall@K: proportion of relevant chunks retrieved in the top K.

Be explicit about the unit represented by K. For the primary retrieval ranking, K refers to ranked chunks. If document-level ranking is also evaluated, calculate document metrics from a clearly defined deduplicated document ranking rather than silently mixing chunk and document ranks.

### 2.3 DeepEval — contextual relevance

The inspected Deep-Evals repository contains an example for ContextualRelevancyMetric.

**Include: Contextual Relevancy.**

Purpose: assess whether the retrieved context is relevant to the input query. This does not conceptually require a generated answer or a reference answer; it uses the query and retrieved context.

Implementation note: DeepEval test-case schemas and metric APIs can require fields beyond the conceptual metric inputs. Check the pinned DeepEval version. If its test-case model requires actual_output even though the selected metric does not use an answer, use a clearly documented neutral compatibility value only if the library supports that safely. Do not generate an answer merely to satisfy an unnecessary field.

### 2.4 RAGAS — non-LLM context metrics

The inspected Ragas-Tutorials repository includes examples for non-LLM context precision and non-LLM context recall with reference contexts.

**Include, subject to API/version verification:**
- NonLLM Context Precision with Reference
- NonLLM Context Recall with Reference

These compare retrieved contexts with reference contexts. They do not require a generated answer or an expected/reference answer. They do require reference contexts: the source passages independently judged to be relevant to the query.

Important distinction:
- A reference context is a source passage from the corpus.
- A reference answer is an answer text.
- They are not interchangeable.

Before implementation, pin a compatible RAGAS version and verify the exact metric class names, imports, sample schema, and scoring semantics. Tutorial code can be version-specific. Do not assume the repository examples run unchanged with the latest package.

### 2.5 Operational and diagnostic measurements

Record these alongside quality metrics:

| Measurement | Purpose |
|---|---|
| Retrieval latency | Time taken by the retrieval operation; record end-to-end and, where practical, per-stage latency |
| Candidate count | Number of candidates entering relevant pipeline stages |
| Result count | Number of chunks finally returned |
| Score distribution | Helps inspect score behavior and separation; diagnostic, not a standalone quality metric |
| Unique document coverage | Number of distinct source documents represented in the retrieved results |

Also retain stage-specific counts and timing where available, including dense/BM25 branch counts, fusion counts, reranker counts, and adaptive-K expansion details.

### 2.6 Optional supplementary lexical metrics

Token Precision, Token Recall, and Token F1 may be calculated by comparing reference-context tokens with retrieved-context tokens.

These are optional diagnostics only, not primary retrieval-quality metrics. Lexical overlap can penalize semantically equivalent paraphrases and can reward passages that share words but do not answer the query. Do not use token overlap as a substitute for judged chunk relevance.

---

## 3. Final Layer 1 metric scope

### Primary metrics
1. Recall@K
2. Precision@K
3. Hit Rate@K
4. MRR@K
5. NDCG@K
6. MAP@K
7. Document Recall@K
8. Chunk Recall@K

### Context metrics
9. DeepEval Contextual Relevancy
10. RAGAS Non-LLM Context Precision with Reference
11. RAGAS Non-LLM Context Recall with Reference

### Performance and diagnostics
12. Retrieval latency
13. Candidate count
14. Result count
15. Score distribution (diagnostic)
16. Unique document coverage

### Optional
- Token Precision
- Token Recall
- Token F1

The first five conventional metrics are implemented directly in our evaluation module; RAGAS and DeepEval are supplementary context-evaluation tools, not replacements for standard ranked-retrieval metrics.

---

## 4. Benchmark dataset design

The agreed direction is a synthetic 100-query benchmark saved as a versioned JSON or JSONL dataset. The questions must be synthetic but grounded in actual SaviraCortex source documents and chunks that are present in the evaluation corpus.

A purely invented question whose answer/source material is not in the indexed corpus cannot provide a valid retrieval test.

### Dataset principles

1. Use a frozen, identifiable corpus snapshot for the benchmark.
2. Generate questions from the actual source documents/chunks.
3. Label relevant documents and chunks independently of the retrieval pipeline.
4. Include all known relevant chunks for each query, not just one convenient passage. Missing relevant labels can make Recall@K misleading.
5. Assign graded relevance where needed for NDCG.
6. Store reference contexts for RAGAS non-LLM context metrics.
7. Keep the benchmark fixed across all experiments.
8. Keep evaluation data and ground-truth judgments separate from retrieval output files.
9. Record corpus/version information so the benchmark can be reproduced.
10. Do not use DBpedia as a required source for this benchmark. The agreed primary source is the controlled SaviraCortex corpus. DBpedia may be considered separately only if there is a specific reason later.

### Proposed canonical sample structure

The following is a design proposal, not yet a generated dataset:

    {
      "dataset_id": "savira_retrieval_eval",
      "dataset_version": "1.0.0",
      "corpus_version": "corpus_snapshot_identifier",
      "samples": [
        {
          "sample_id": "Q001",
          "query": "Synthetic question grounded in the corpus",
          "ground_truth": {
            "relevant_documents": [
              {
                "document_id": "DOC001",
                "relevance_grade": 3
              }
            ],
            "relevant_chunks": [
              {
                "chunk_id": "stable-runtime-chunk-id",
                "document_id": "DOC001",
                "relevance_grade": 3,
                "reference_context": "Exact or faithfully preserved source passage"
              }
            ]
          },
          "reference_answer": null,
          "metadata": {
            "category": "direct_factual",
            "split": "test"
          }
        }
      ]
    }

Required sample fields:
- sample_id
- query
- ground-truth relevant document IDs
- ground-truth relevant chunk IDs
- relevance grades
- reference contexts

reference_answer remains null/not required for Layer 1. It can be added in a later dataset version if Layer 2 needs it.

Potential query categories can be selected when constructing the benchmark. A previously discussed candidate distribution was:
- 20 direct factual
- 20 semantic/conceptual
- 15 multi-hop
- 15 entity/relationship
- 10 keyword-sensitive
- 10 ambiguous/paraphrased
- 10 complex multi-document

This distribution is a proposal, not yet locked. Final categories should reflect the actual corpus and should not force question types unsupported by the corpus.

### Retrieval run output

Store actual retrieval outputs separately from the ground-truth dataset, keyed by sample and experiment:

    {
      "sample_id": "Q001",
      "experiment_id": "hybrid_reranking_v1",
      "retrieved_chunks": [
        {
          "chunk_id": "stable-runtime-chunk-id",
          "rank": 1,
          "score": 0.92,
          "page_content": "Retrieved source passage"
        }
      ],
      "latency_ms": 123.4
    }

This separation prevents accidental modification of ground truth when rerunning experiments.

---

## 5. Retrieval system under evaluation

The existing SaviraCortex code has two useful evaluation levels.

### Component-level retrieval

The lower-level HybridRetrievalPipeline.search() supports:
- mode = dense
- mode = bm25
- mode = hybrid

It returns ranked results with page content and metadata. This is useful for controlled component comparisons.

### Full retrieval orchestration

RetrievalOrchestrator.retrieve() runs the broader retrieval flow, including:
- authorization-scoped document catalogue
- multi-query generation
- candidate document generation
- retrieval branches
- global fusion
- cross-encoder reranking
- adaptive K selection/expansion

It returns final selected candidates and useful stage counts/details. It retrieves context; it does not generate an answer.

The orchestrator requires a valid organization_id and user_id and uses authorization to determine visible documents. Evaluation must use a dedicated, controlled evaluation organization/user or an equivalent safe test setup with access to the benchmark corpus.

### Planned experiment sequence

Run the same benchmark, corpus snapshot, relevance judgments, authorization scope, and evaluation settings for every experiment.

| Experiment | Configuration | Purpose |
|---|---|---|
| E1 | Dense only | Establish dense retrieval baseline |
| E2 | BM25 only | Establish lexical retrieval baseline |
| E3 | Hybrid retrieval | Measure benefit of combining dense and BM25 |
| E4 | Hybrid + global fusion | Measure fusion contribution |
| E5 | Hybrid + global fusion + cross-encoder reranking | Measure reranking contribution |
| E6 | Full orchestrator, including multi-query/candidate generation/adaptive K | Measure end-to-end retrieval performance |

Where the implementation makes a stage inseparable from another, document that constraint rather than pretending it is an independent ablation.

---

## 6. Stable chunk identity — critical implementation requirement

The current retrieval implementation needs careful identity alignment between benchmark labels and runtime results.

The inspected GlobalResultFusion logic derives chunk identity from:
- document_version_id + chunk_index, or
- document_id + chunk_index, or
- a legacy fallback involving source/page/content.

The fusion result exposes a chunk_id derived from this identity. CrossEncoderReranker expects and preserves chunk_id, page_content, metadata, global rank/score, and provenance.

However, lower-level HybridRetrievalPipeline.search() results expose metadata and page content and may not expose a top-level stable chunk_id directly.

Before building labels or running metrics:
1. Inspect the ingestion/indexing code and actual stored chunk metadata.
2. Confirm the stable ID used by every retrieval branch.
3. Confirm that the ID is stable across re-indexing of the frozen corpus snapshot.
4. Ensure benchmark ground-truth IDs exactly match runtime IDs.
5. If necessary, make a small explicit-ID metadata/fusion change after reviewing the indexing contract.

Do not generate the benchmark using IDs that cannot be recovered from actual retrieval results.

---

## 7. Evaluator architecture

The evaluation implementation should remain a small, explicit module rather than introducing an unnecessary framework or abstraction layer.

Proposed responsibilities:

1. Dataset loader: reads and validates the canonical JSON/JSONL benchmark.
2. Retrieval runner: invokes the existing pipeline/orchestrator for each query and experiment.
3. Result normalizer: extracts stable chunk/document IDs, rank, score, text, and timing.
4. Metric calculator: computes Recall@K, Precision@K, Hit Rate@K, MRR@K, NDCG@K, MAP@K, and document/chunk recall.
5. Context metric adapters: convert the same sample and retrieval result into the pinned DeepEval/RAGAS input structures.
6. Result writer: saves per-query outputs and aggregate experiment reports.
7. Evaluator tests: validate formulas against manually calculated examples.

Avoid adding a generated-answer stage or a new general-purpose LLM abstraction for Layer 1. If a DeepEval adapter needs a compatibility field, document the reason and do not actually generate an answer.

Configuration for any evaluation LLM judge should use app/core/config.py if one becomes necessary. Potential EVAL_LLM_* overrides can default to existing OPENAI_* settings. However, the primary ID-based metrics do not need an LLM or LLM credentials. Verify whether the chosen Contextual Relevancy and RAGAS non-LLM implementations need model configuration in the pinned versions before adding dependencies/configuration.

RAGAS and DeepEval are not currently assumed to be installed in the project. Check pyproject.toml and uv.lock, pin compatible versions, and update the lockfile only when implementation is authorized.

---

## 8. Validate the evaluator before trusting benchmark results

Write deterministic unit tests using small hand-constructed examples with known expected metric values.

At minimum, cover:
- All relevant chunks retrieved.
- No relevant chunks retrieved.
- First result is relevant.
- First relevant result appears at the last evaluated rank.
- Relevant and irrelevant chunks are interleaved.
- Fewer than K results are returned.
- Multiple relevance grades for NDCG.
- Duplicate chunk IDs, if duplicates can occur in the retrieval output.
- No relevant ground-truth chunks / invalid sample handling.

Manually calculate expected values and compare them with the metric implementation. Define edge-case behavior explicitly rather than silently returning misleading numbers.

Also validate:
- Dataset schema and unique sample IDs.
- Every ground-truth chunk ID maps to the frozen corpus.
- Every reference context corresponds to the labeled source chunk.
- The evaluation corpus is visible to the evaluation organization/user.
- The same corpus snapshot and settings are used for all ablations.

---

## 9. Reporting

For each experiment, report:
- Per-query metrics.
- Macro-average metrics across the benchmark.
- Metrics by query category.
- Metrics at each K cutoff.
- Retrieval latency summary (mean and useful percentiles such as p50/p95).
- Stage counts and diagnostic measurements.
- Context metric scores where supported.

Compare experiments side by side to identify which components improve retrieval quality and what latency/candidate-count trade-offs they introduce.

Do not claim that one metric alone proves the pipeline is good. Interpret recall, precision, ranking, contextual relevance, and latency together.

---

## 10. Layer 2 — future end-to-end RAG evaluation

After Layer 1 is implemented, validated, and run, build the answer generator pipeline.

At that point each evaluation sample/run can include:
- user query
- retrieved contexts
- generated answer (actual_output)
- expected/reference answer
- reference contexts
- relevant source/chunk identifiers

Then add answer-dependent evaluations such as:
- DeepEval Contextual Precision
- DeepEval Contextual Recall
- Answer Relevancy
- Faithfulness
- Answer correctness / GEval-style correctness where suitable
- RAGAS Faithfulness
- RAGAS Answer Relevancy
- RAGAS LLM-based Context Precision and Context Recall
- Other metrics supported by the pinned library versions and the final evaluation objective

Layer 2 evaluates the complete RAG behavior, including whether the generated answer is supported by retrieved material and whether it answers the question correctly.

Layer 2 does not replace Layer 1. Keep the retrieval-only benchmark and metrics so retrieval regressions can be diagnosed separately from generation quality.

---

## 11. Agreed next steps

The frozen corpus and the first candidate-generation utility are now in place.

1. Run `evaluation/scripts/generate_synthetic_dataset.py` against the locked 485-chunk corpus.
2. Review whether the proposed 100-query category distribution is actually supported by the seven source documents.
3. Independently review every generated question and candidate source passage; reject unsupported or ambiguous questions and identify all relevant chunks.
4. Assign relevance grades only after human judgment. Keep reference answers null for Layer 1.
5. Promote the approved candidates into the canonical versioned JSON/JSONL benchmark.
6. Implement dataset validation and loading.
7. Implement the retrieval runner and per-experiment result storage.
8. Implement and unit-test the deterministic retrieval metrics.
9. Verify and integrate DeepEval Contextual Relevancy and RAGAS non-LLM context metrics with pinned versions.
10. Run E1–E6 and compare results.
11. Review Layer 1 findings before designing the answer generator and Layer 2.

The candidate generator reads and validates the exact locked Qdrant corpus before calling the configured LLM. It writes candidate questions and proposed source-chunk links only. It does not generate reference answers, assign relevance grades, modify Qdrant, or implement the retrieval evaluator.

**Current decision (updated 5 November 2026):** Layer 1 evaluation scope is agreed and the seven-document, 485-chunk corpus is locked and full-text verified. The workspace now contains evidence-group candidates, generated question datasets, relevance-judgment artifacts, metric code, and retrieval evaluation/scoring scripts. The remaining work is to audit and reuse these artifacts, independently review relevance judgments and benchmark readiness, validate metric formulas and edge cases, and run/report reproducible experiments. The existence of these files does not by itself establish benchmark approval or valid final scores.

---

## Repository checkpoint — 5 November 2026

The retrieval evaluation work has progressed beyond the initial planning stage. The workspace currently contains:

- A frozen chunk catalogue and corpus lock.
- The evidence-group candidate dataset.
- Generated question datasets, including a cleaned output.
- Relevance-judgment artifacts, including a hybrid-successful-run judgment file.
- Metric implementation in `evaluation/metrics.py`.
- Retrieval capture, evaluation runner, worker, scoring, and judgment-preparation scripts under `evaluation/`.

This is a filesystem inventory, not a claim that the benchmark is fully approved or that the latest evaluator run has passed. Before treating results as authoritative, audit the existing datasets and scripts, confirm the frozen corpus identity, independently review relevance judgments for completeness and correctness, validate metric formulas/edge cases, and run a reproducible benchmark with a recorded configuration and report.

The end-to-end RAG workflow is now implemented and locally verified. Layer 1 retrieval evaluation is the next project milestone. Backend/API and frontend integration follow; Layer 2 answer-quality evaluation should be added after the application workflow contract is stable.

Do not overwrite existing generated datasets, judgment files, or experiment results while auditing. Create versioned outputs for new runs.