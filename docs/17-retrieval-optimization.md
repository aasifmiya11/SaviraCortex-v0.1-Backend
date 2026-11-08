# 17. Retrieval Optimization and Ranking

The retrieval path combines first-stage dense/lexical search, rank fusion, a cross-encoder and adaptive query expansion.

## Dense retrieval

`dense.py` queries the configured Qdrant chunk collection using `JinaEmbeddingClient`. Passage vectors use Jina's `retrieval.passage` task and search queries use `retrieval.query`; the configured default is `jina-embeddings-v5-text-small` with 1024 dimensions. Filters include organization ID, optional document/user filters, lifecycle status and candidate version IDs. The orchestrator supplies the exact authorized candidate version IDs and disables the second status filter because candidate generation has already applied lifecycle scope.

## Lexical retrieval

`qdrant_bm25.py` uses Qdrant's native full-text `TextQuery` against the indexed `page_content` field. It applies the same organization/document/user/status/version filters. This is the active lexical path; the presence of a local SQLite BM25-related artifact does not make it the retrieval source used by this pipeline.

## Hybrid and rank fusion

`HybridRetrievalPipeline` supports `hybrid`, `bm25`, and `dense` modes. Hybrid mode combines dense and BM25 result lists with reciprocal-rank fusion (RRF); default channel weights are 1.0 each and the default RRF constant is 60. The lower-level fusion deduplicates by version-aware chunk identity. `GlobalResultFusion` then merges results across generated-query branches using RRF and retains branch/query provenance for each chunk.

RRF combines rank positions rather than assuming raw scores from different retrieval systems are directly comparable.

## Cross-encoder reranking

`CrossEncoderReranker` sends the query and fused candidate texts to Jina's `/rerank` endpoint using `jina-reranker-v2-base-multilingual` by default. It requests scores for all candidates, maps API result indices back to the original candidate records, sorts by relevance score, and preserves global rank and provenance metadata. An injectable scorer remains available for isolated tests.

## Adaptive selection and query expansion

`AdaptiveKSelector` defaults to `k_min=3`, `k_max=10`, `score_threshold=0.6`, and at most two expansion rounds. It selects only candidates whose reranker score meets the threshold, then caps the list at `k_max`. If fewer than `k_min` qualify and rounds remain, the orchestrator asks the multi-query agent for additional non-duplicate queries, including prior queries and retrieved chunk excerpts as context, then repeats candidate generation and retrieval.

The reranker threshold is model/configuration-specific; it is not a calibrated probability of relevance. Calibrate it against held-out relevance judgments before production use.

## Tuning methodology

- Establish a representative evaluation query set and relevance judgments.
- Measure recall before reranking and ranking quality after reranking.
- Track latency, vector database load, LLM query-expansion cost and reranker throughput.
- Change one stage at a time.
- Keep organization, authorization and version filters invariant during optimization.
