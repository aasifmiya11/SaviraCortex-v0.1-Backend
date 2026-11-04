# 17. Retrieval Optimization

The retrieval package includes several independent ranking and efficiency techniques.

## Dense retrieval

`dense.py` queries Qdrant using embeddings to find semantically similar chunks. It is useful when the user's wording differs from the document's wording.

## Lexical retrieval

`qdrant_bm25.py` provides lexical/BM25-style matching. It complements semantic retrieval for exact terms, names, identifiers and domain vocabulary.

## Fusion

`fusion.py` and `global_fusion.py` combine rankings from different retrieval channels and generated query variants. Fusion uses ranks rather than treating scores from different retrieval systems as directly comparable. Confirm the configured fusion constant and deduplication behavior in source before changing ranking.

## Cross-encoder reranking

`cross_encoder_reranker.py` reranks a smaller candidate set using a query/document relevance model. This is more computationally expensive than first-stage retrieval, so it is applied after candidate generation and fusion.

## Adaptive retrieval depth

`adaptive_k_selector.py` selects how many candidates to retrieve/retain based on its input signals and configured limits. Tests cover selector behavior. Treat all thresholds and caps as model/system tuning parameters, not universal constants.

## Tuning methodology

- Establish a representative evaluation query set.
- Measure recall before reranking and ranking quality after reranking.
- Track latency, vector database load, LLM query-expansion cost and reranker throughput.
- Change one stage at a time.
- Keep authorization and version filters invariant during optimization.
