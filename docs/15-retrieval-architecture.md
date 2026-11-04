# 15. Retrieval Architecture

## Overview

`RetrievalOrchestrator` in `app/services/retrieval/retrieval_service.py` coordinates authorization, multi-query generation, summary-based candidate selection, chunk retrieval, global fusion, cross-encoder reranking, adaptive selection and optional query expansion. The lower-level `HybridRetrievalPipeline` performs dense and/or Qdrant BM25 chunk retrieval.

## Request defaults

The orchestrator's `retrieve()` defaults are `top_k=10`, `candidate_k=20`, `mode="hybrid"`, and `rrf_k=60`. Retrieval branches run with a concurrency limit of six by default. Supported modes are `hybrid`, `bm25`, and `dense`.

## Stages

1. Validate query, UUIDs, limits and retrieval mode.
2. Resolve the caller's authorized active/superseded version catalogue through the synchronous `AuthorizationService`.
3. Convert the catalogue into the multi-query agent's typed `AvailableDocuments` input.
4. Generate contextualized queries with version scopes and optional target years.
5. For each query, search document summaries in Qdrant using only authorized, lifecycle-compatible version IDs; validate hits against the PostgreSQL-derived catalogue.
6. For each candidate set, run dense, lexical/BM25 or hybrid chunk retrieval using organization and exact candidate-version filters.
7. Merge query branches with global reciprocal-rank fusion while retaining query provenance.
8. Rerank fused chunks with a cross-encoder.
9. Select chunks above the adaptive score threshold, capped by the selector's maximum.
10. If too few chunks qualify and expansion rounds remain, ask the multi-query agent for additional non-duplicate queries using previous queries and retrieved chunk text, then repeat candidate retrieval and ranking.

## Main modules

| Module | Responsibility |
|---|---|
| `app/services/retrieval/retrieval_service.py` | End-to-end retrieval orchestration and query expansion |
| `pipeline.py` | Dense/BM25/hybrid chunk search |
| `dense.py` | Dense vector retrieval |
| `qdrant_bm25.py` | Qdrant full-text/BM25 retrieval |
| `fusion.py` | RRF within the lower-level hybrid pipeline |
| `global_fusion.py` | RRF across generated-query branches and provenance collection |
| `cross_encoder_reranker.py` | Cross-encoder reranking |
| `adaptive_k_selector.py` | Score threshold, result cap and expansion signal |
| `candidate_document_generator.py` | Authorized document/version candidates from summary similarity |

## Authorization boundary and cache integration

The orchestrator currently calls `AuthorizationService.get_authorized_document_catalog()` directly. The separate Redis-backed `AuthorizationCacheService` is not part of this orchestrator's current dependency path. The authorized catalogue and exact candidate version IDs constrain candidate generation and chunk queries; vector similarity is never an authorization decision.

## Result interpretation

The returned dictionary includes selected candidates, counts, generated queries, branch statistics, expansion metadata, and any candidate-generation error. Results are chunks, not necessarily complete documents. Page metadata, document/version identifiers and per-query provenance support downstream attribution. Answer generation and user-facing citation formatting are outside this orchestrator.
