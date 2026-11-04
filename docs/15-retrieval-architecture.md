# 15. Retrieval Architecture

## Overview

Retrieval is coordinated by `app/services/retrieval/retrieval_service.py` and the RAG modules under `app/rag/retrieval/`. The retrieval pipeline is designed around an authorized document scope and available document/version catalogue.

## Stages

1. Resolve user/organization access scope.
2. Load the eligible document/version catalogue.
3. Generate multiple query variants, preserving version intent.
4. Generate candidate document/version constraints.
5. Retrieve dense semantic and lexical/BM25 candidates within the candidate scope.
6. Fuse rankings across queries and retrieval channels.
7. Rerank the leading candidates with a cross-encoder.
8. Adapt retrieval depth where configured and return selected chunks with provenance metadata.

## Main modules

| Module | Responsibility |
|---|---|
| `pipeline.py` | Retrieval orchestration |
| `dense.py` | Dense vector retrieval |
| `qdrant_bm25.py` | Qdrant lexical/BM25 retrieval |
| `fusion.py` | Per-query/channel rank fusion |
| `global_fusion.py` | Global fusion across generated queries |
| `cross_encoder_reranker.py` | Cross-encoder reranking |
| `adaptive_k_selector.py` | Selects retrieval depth |
| `candidate_document_generator.py` | Builds candidate document/version scope |

## Authorization boundary

The authorized document IDs and catalogue constrain candidate generation and vector queries. Never bypass this boundary for recall improvements. A document returned by Qdrant must still be eligible under the current tenant and lifecycle policy.

## Result interpretation

Results are chunks, not necessarily complete documents. Page metadata and document/version identifiers provide provenance. Downstream answer generation/citation behavior is outside the reviewed service surface unless implemented by a caller.
