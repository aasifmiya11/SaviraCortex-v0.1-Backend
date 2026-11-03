from __future__ import annotations

from collections import defaultdict
from typing import Any


def _chunk_identity(result: dict[str, Any]) -> str:
    """Build a stable identity for one retrieved chunk."""

    metadata = result.get("metadata") or {}
    document_version_id = metadata.get("document_version_id")
    chunk_index = metadata.get("chunk_index")

    if document_version_id is not None and chunk_index is not None:
        return f"{document_version_id}:{chunk_index}"

    document_id = metadata.get("document_id")
    if document_id is not None and chunk_index is not None:
        return f"{document_id}:{chunk_index}"

    # Include document identity in the legacy fallback so identical
    # filenames/pages/content from different documents are not merged.
    document_identity = document_id or document_version_id
    identity_prefix = f"{document_identity}:" if document_identity is not None else ""
    return (
        f"{identity_prefix}"
        f"{metadata.get('source', '')}:"
        f"{metadata.get('page', '')}:"
        f"{result.get('page_content', '')}"
    )


class GlobalResultFusion:
    """Merge independently ranked query branches using global RRF."""

    def fuse(
        self,
        branch_results: list[dict[str, Any]],
        top_k: int = 20,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        if not isinstance(branch_results, list):
            raise ValueError("branch_results must be a list.")
        if isinstance(top_k, bool) or top_k < 1:
            raise ValueError("top_k must be at least 1.")
        if isinstance(rrf_k, bool) or rrf_k < 1:
            raise ValueError("rrf_k must be at least 1.")

        scores: defaultdict[str, float] = defaultdict(float)
        chunks: dict[str, dict[str, Any]] = {}
        provenance: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

        for branch_index, branch in enumerate(branch_results):
            if not isinstance(branch, dict):
                raise ValueError(
                    f"Branch {branch_index} must be a dictionary."
                )

            query = branch.get("query")
            results = branch.get("results")
            if not isinstance(query, str):
                raise ValueError(
                    f"Branch {branch_index} is missing a string query."
                )
            if not isinstance(results, list):
                raise ValueError(
                    f"Branch {branch_index} is missing a results list."
                )

            for position, result in enumerate(results, start=1):
                if not isinstance(result, dict):
                    raise ValueError(
                        f"Branch {branch_index} result {position} "
                        "must be a dictionary."
                    )

                rank = result.get("rank")
                if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
                    raise ValueError(
                        f"Branch {branch_index} result {position} "
                        "must have a positive integer rank."
                    )

                branch_score = result.get("score")
                if isinstance(branch_score, bool) or not isinstance(
                    branch_score, (int, float)
                ):
                    raise ValueError(
                        f"Branch {branch_index} result {position} "
                        "must have a numeric score."
                    )

                chunk_id = _chunk_identity(result)
                scores[chunk_id] += 1.0 / (rrf_k + rank)
                chunks.setdefault(chunk_id, result)
                provenance[chunk_id].append(
                    {
                        "query": query,
                        "branch_index": branch_index,
                        "rank": rank,
                        "score": float(branch_score),
                    }
                )

        ranked_chunks = sorted(
            scores,
            key=lambda chunk_id: (
                -scores[chunk_id],
                min(item["rank"] for item in provenance[chunk_id]),
                chunk_id,
            ),
        )[:top_k]

        return [
            {
                "global_rank": rank,
                "global_rrf_score": scores[chunk_id],
                "chunk_id": chunk_id,
                "page_content": chunks[chunk_id].get("page_content", ""),
                "metadata": dict(chunks[chunk_id].get("metadata") or {}),
                "provenance": provenance[chunk_id],
            }
            for rank, chunk_id in enumerate(ranked_chunks, start=1)
        ]


global_result_fusion = GlobalResultFusion()
