from collections import defaultdict
from langchain_core.documents import Document

def _key(doc: Document) -> str:
    md = doc.metadata or {}
    if md.get("document_id") is not None and md.get("chunk_index") is not None:
        return f"{md['document_id']}:{md['chunk_index']}"
    return f"{md.get('source','')}:{md.get('page','')}:{doc.page_content}"

def reciprocal_rank_fusion(ranked_lists: list[list[tuple[Document, float]]],
                           k: int = 60, weights: list[float] | None = None
                           ) -> list[tuple[Document, float]]:
    if k < 1:
        raise ValueError("RRF constant k must be at least 1.")
    weights = weights if weights is not None else [1.0] * len(ranked_lists)
    if len(weights) != len(ranked_lists):
        raise ValueError("weights must match the number of ranked lists.")
    scores, docs = defaultdict(float), {}
    for result_list, weight in zip(ranked_lists, weights):
        for rank, (doc, _raw_score) in enumerate(result_list, 1):
            key = _key(doc)
            scores[key] += float(weight) / (k + rank)
            docs.setdefault(key, doc)
    return [(docs[key], scores[key]) for key in
            sorted(scores, key=scores.get, reverse=True)]
