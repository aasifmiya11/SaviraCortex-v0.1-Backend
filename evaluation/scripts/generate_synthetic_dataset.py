"""Generate Layer 1 query candidates from the frozen, indexed evaluation corpus.

This script proposes questions and source passages only. It deliberately does not
create reference answers or assign ground-truth relevance grades. Human review is
required before candidates can become benchmark ground truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = logging.getLogger("evaluation.generate")
LOCK_PATH = ROOT / "evaluation" / "datasets" / "corpus_lock.json"
CATALOGUE_PATH = ROOT / "evaluation" / "datasets" / "chunk_catalogue.json"

CATEGORY_COUNTS = {
    "direct_factual": 20,
    "semantic_conceptual": 20,
    "multi_hop": 15,
    "entity_relationship": 15,
    "keyword_sensitive": 10,
    "ambiguous_paraphrased": 10,
    "complex_multi_document": 10,
}
MULTI_SOURCE_CATEGORIES = {"multi_hop", "complex_multi_document"}

CATEGORY_GUIDANCE = {
    "direct_factual": "Ask for one explicit fact stated in the source.",
    "semantic_conceptual": "Ask for the meaning, purpose, explanation, or concept described by the source.",
    "multi_hop": "Require combining two distinct passages from the same document; neither passage alone should be sufficient.",
    "entity_relationship": "Ask about a relationship, role, comparison, or connection between named entities in the source.",
    "keyword_sensitive": "Use precise technical vocabulary or a meaningful term distinction present in the source.",
    "ambiguous_paraphrased": "Use indirect or alternate wording for a clear source-supported information need; do not make the question genuinely ambiguous or unanswerable.",
    "complex_multi_document": "Require combining evidence from both supplied documents; neither document alone should be sufficient.",
}


def load_environment() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")


def configure_isolation() -> dict[str, str]:
    mapping = {
        "SAVIRACORTEX_EVAL_QDRANT_COLLECTION": "QDRANT_COLLECTION_NAME",
        "SAVIRACORTEX_EVAL_QDRANT_SUMMARY_COLLECTION": "QDRANT_SUMMARY_COLLECTION_NAME",
        "SAVIRACORTEX_EVAL_B2_STORAGE_PREFIX": "B2_STORAGE_PREFIX",
    }
    missing = [key for key in mapping if not os.getenv(key, "").strip()]
    if missing:
        raise RuntimeError("Missing evaluation settings: " + ", ".join(missing))
    production = {
        "QDRANT_COLLECTION_NAME": os.getenv("QDRANT_COLLECTION_NAME"),
        "QDRANT_SUMMARY_COLLECTION_NAME": os.getenv("QDRANT_SUMMARY_COLLECTION_NAME"),
        "B2_STORAGE_PREFIX": os.getenv("B2_STORAGE_PREFIX", "voice-ai/"),
    }
    evaluation = {app: os.environ[key].strip() for key, app in mapping.items()}
    for key, value in evaluation.items():
        if production.get(key) and production[key] == value:
            raise RuntimeError(f"{key} must be evaluation-only.")
    os.environ.update(evaluation)
    return evaluation


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_chunk_text(value: str) -> str:
    """Normalize line endings and tolerate one optional terminal newline.

    Internal whitespace, blank lines, and all other characters remain significant.
    """
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized[:-1] if normalized.endswith("\n") else normalized


def load_frozen_corpus() -> tuple[dict[str, Any], dict[str, Any]]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    catalogue = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    if lock.get("status") != "locked_for_benchmark":
        raise RuntimeError("The corpus lock is not marked locked_for_benchmark.")
    if lock.get("full_text_status") != "verified_complete":
        raise RuntimeError("The frozen corpus does not have verified full chunk text.")
    if catalogue.get("catalogue_status") != "verified_complete":
        raise RuntimeError("The chunk catalogue is not marked verified_complete.")

    expected_versions = {
        item["document_version_id"] for item in lock.get("source_documents", [])
    }
    if not expected_versions:
        raise RuntimeError("The corpus lock contains no source document versions.")
    chunks = catalogue.get("chunks")
    if not isinstance(chunks, list):
        raise RuntimeError("The chunk catalogue has no chunks array.")
    locked_chunks = [
        item for item in chunks
        if item.get("document_version_id") in expected_versions
    ]
    if len(locked_chunks) != lock.get("qdrant_point_count"):
        raise RuntimeError("Locked catalogue chunk count does not match corpus_lock.json.")
    expected_ids = {item.get("chunk_id") for item in locked_chunks}
    if None in expected_ids or len(expected_ids) != len(locked_chunks):
        raise RuntimeError("The locked catalogue contains missing or duplicate chunk IDs.")
    return lock, catalogue


def read_indexed_chunks(organization_id: UUID) -> list[dict[str, Any]]:
    from qdrant_client import models
    from app.core.config import settings
    from app.rag.vector_stores.qdrant import client as store

    query_filter = models.Filter(must=[
        models.FieldCondition(
            key="metadata.organization_id",
            match=models.MatchValue(value=str(organization_id)),
        )
    ])
    records: list[dict[str, Any]] = []
    offset = None
    while True:
        points, offset = store.client.scroll(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            metadata = payload.get("metadata")
            content = payload.get("page_content")
            if not isinstance(metadata, dict) or not isinstance(content, str):
                continue
            doc_id = metadata.get("document_id")
            version_id = metadata.get("document_version_id")
            chunk_index = metadata.get("chunk_index")
            if doc_id is None or version_id is None or chunk_index is None:
                continue
            records.append({
                "qdrant_point_id": str(point.id),
                "page_content": content,
                "metadata": dict(metadata),
                "chunk_id": f"{version_id}:{int(chunk_index)}",
                "document_id": str(doc_id),
                "document_version_id": str(version_id),
                "chunk_index": int(chunk_index),
                "organization_id": str(metadata.get("organization_id") or ""),
                "status": metadata.get("status", payload.get("status")),
            })
        if offset is None:
            break
    records.sort(key=lambda item: (item["document_version_id"], item["chunk_index"]))
    return records


def validate_live_corpus(
    records: list[dict[str, Any]],
    lock: dict[str, Any],
    catalogue: dict[str, Any],
    organization_id: UUID,
    collection_name: str,
) -> list[dict[str, Any]]:
    if str(organization_id) != lock.get("organization_id"):
        raise RuntimeError("Organization ID does not match the frozen corpus lock.")
    if collection_name != lock.get("qdrant_collection"):
        raise RuntimeError("Qdrant collection does not match the frozen corpus lock.")

    locked_versions = {item["document_version_id"] for item in lock["source_documents"]}
    live = [item for item in records if item["document_version_id"] in locked_versions]
    expected_by_id = {
        item["chunk_id"]: item for item in catalogue["chunks"]
        if item.get("document_version_id") in locked_versions
    }
    live_by_id: dict[str, dict[str, Any]] = {}
    for item in live:
        chunk_id = item["chunk_id"]
        if chunk_id in live_by_id:
            raise RuntimeError(f"Duplicate live chunk identity: {chunk_id}")
        live_by_id[chunk_id] = item

    expected_ids, live_ids = set(expected_by_id), set(live_by_id)
    missing, unexpected = sorted(expected_ids - live_ids), sorted(live_ids - expected_ids)
    if missing or unexpected:
        raise RuntimeError(
            "Live Qdrant chunks do not match the frozen catalogue "
            f"(missing={len(missing)}, unexpected={len(unexpected)})."
        )

    verified = []
    for chunk_id, expected in expected_by_id.items():
        actual = live_by_id[chunk_id]
        checks = {
            "qdrant_point_id": expected.get("qdrant_point_id"),
            "document_id": expected.get("document_id"),
            "document_version_id": expected.get("document_version_id"),
            "chunk_index": expected.get("chunk_index"),
            "organization_id": expected.get("organization_id"),
        }
        for field, expected_value in checks.items():
            if actual.get(field) != expected_value:
                raise RuntimeError(f"Frozen corpus mismatch for {chunk_id}: {field} differs.")
        expected_text = expected.get("chunk_text")
        actual_text = actual["page_content"]
        if (
            not isinstance(expected_text, str)
            or normalize_chunk_text(actual_text) != normalize_chunk_text(expected_text)
        ):
            raise RuntimeError(f"Full chunk text mismatch for {chunk_id}.")
        verified.append({
            **actual,
            "source_pdf": expected["source_filename"],
            "page": expected.get("page"),
        })

    verified.sort(key=lambda item: (item["document_version_id"], item["chunk_index"]))
    if len(verified) != lock["qdrant_point_count"]:
        raise RuntimeError("Verified live chunk count does not match the corpus lock.")
    LOG.info(
        "Verified frozen corpus: %d chunks across %d document versions.",
        len(verified), len(locked_versions),
    )
    return verified


def stable_order(items: list[dict[str, Any]], seed: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: sha256(f"{seed}:{item['chunk_id']}"))


def build_source_plans(
    records: list[dict[str, Any]],
    category: str,
    count: int,
    seed: str,
    max_context_chars: int,
) -> list[dict[str, Any]]:
    by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        by_document[item["document_version_id"]].append(item)
    document_ids = sorted(by_document)
    category_seed = f"{seed}:{category}"
    for document_id in document_ids:
        by_document[document_id] = stable_order(
            by_document[document_id], category_seed
        )
    all_chunks = stable_order(records, category_seed)

    plans = []
    for index in range(count):
        if category == "multi_hop":
            doc_id = document_ids[index % len(document_ids)]
            pool = sorted(by_document[doc_id], key=lambda item: item["chunk_index"])
            start = (index * 2) % max(1, len(pool) - 1)
            selected = [pool[start], pool[start + 1]]
        elif category == "complex_multi_document":
            if len(document_ids) < 2:
                raise RuntimeError("complex_multi_document requires at least two documents.")
            first_doc = document_ids[index % len(document_ids)]
            second_doc = document_ids[(index + 1) % len(document_ids)]
            first = by_document[first_doc][(index * 2) % len(by_document[first_doc])]
            second = by_document[second_doc][(index * 2 + 1) % len(by_document[second_doc])]
            selected = [first, second]
        else:
            selected = [all_chunks[index % len(all_chunks)]]

        contexts = []
        for item in selected:
            text = item["page_content"]
            contexts.append({
                "chunk_id": item["chunk_id"],
                "document_id": item["document_id"],
                "document_version_id": item["document_version_id"],
                "source_pdf": item["source_pdf"],
                "page": item.get("page"),
                "text": text[:max_context_chars],
                "text_truncated_for_prompt": len(text) > max_context_chars,
            })
        plans.append({
            "plan_id": f"{category}-{index + 1:03d}",
            "category": category,
            "contexts": contexts,
        })
    return plans


def build_generator():
    from langchain_openai import ChatOpenAI
    api_key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_MODEL are required.")
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": 0.3,
        "max_retries": 2,
        "timeout": 120,
    }
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs), model


def response_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "") for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    raise ValueError("The model returned an unsupported response format.")


def parse_model_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*" + re.escape(fence) + r"$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The model response did not contain a JSON object.")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict) or not isinstance(value.get("questions"), list):
        raise ValueError("The model response must contain a questions array.")
    return value


def generate_category(
    generator: Any,
    plans: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    category = plans[0]["category"]
    plan_payload = json.dumps(plans, ensure_ascii=False)
    prompt = f"""
You are creating candidate questions for a retrieval-only benchmark.
Generate exactly one natural user question for each plan below.

Category: {category}
Category guidance: {CATEGORY_GUIDANCE[category]}

Rules:
- Use only facts supported by the supplied source context.
- Do not invent names, facts, relationships, numbers, or premises.
- Do not answer the question or return an expected/reference answer.
- Do not use outside knowledge.
- Keep each question self-contained and realistically phrased.
- A multi_hop question must genuinely require both supplied chunks from the same document.
- A complex_multi_document question must genuinely require evidence from both supplied documents.
- For other categories, use only the supplied chunk and do not force unsupported complexity.
- Return only JSON with this shape:
  {{"questions":[{{"plan_id":"...","query":"...","source_chunk_ids":["..."]}}]}}
- source_chunk_ids must contain only IDs supplied in that plan and only passages genuinely needed.
- Return one item for every plan_id, without duplicates.

Plans and source passages:
{plan_payload}
"""
    parsed = parse_model_json(response_text(generator.invoke(prompt)))
    by_plan = {plan["plan_id"]: plan for plan in plans}
    accepted, rejected = [], []
    seen_plans: set[str] = set()

    for row in parsed["questions"]:
        if not isinstance(row, dict):
            rejected.append({"reason": "question_item_not_object", "category": category})
            continue
        plan_id = str(row.get("plan_id") or "").strip()
        query = str(row.get("query") or "").strip()
        source_ids = row.get("source_chunk_ids")
        if plan_id not in by_plan:
            rejected.append({"plan_id": plan_id, "reason": "unknown_plan_id", "category": category})
            continue
        if plan_id in seen_plans:
            rejected.append({"plan_id": plan_id, "reason": "duplicate_plan_id", "category": category})
            continue
        seen_plans.add(plan_id)
        plan = by_plan[plan_id]
        allowed_ids = {context["chunk_id"] for context in plan["contexts"]}
        if not query or not isinstance(source_ids, list):
            rejected.append({"plan_id": plan_id, "reason": "missing_query_or_source_ids", "category": category})
            continue
        selected_ids = list(dict.fromkeys(
            value for value in source_ids if isinstance(value, str)
        ))
        if not selected_ids or any(value not in allowed_ids for value in selected_ids):
            rejected.append({"plan_id": plan_id, "reason": "invalid_source_chunk_ids", "category": category})
            continue
        if category in MULTI_SOURCE_CATEGORIES and len(selected_ids) < 2:
            rejected.append({"plan_id": plan_id, "reason": "multi_source_question_has_fewer_than_two_chunks", "category": category})
            continue
        selected_contexts = [
            context for context in plan["contexts"] if context["chunk_id"] in selected_ids
        ]
        if category == "complex_multi_document" and (
            len({context["document_id"] for context in selected_contexts}) < 2
        ):
            rejected.append({"plan_id": plan_id, "reason": "question_does_not_use_multiple_documents", "category": category})
            continue
        accepted.append({
            "query": query,
            "category": category,
            "candidate_contexts": selected_contexts,
            "plan_id": plan_id,
        })

    for plan_id in sorted(set(by_plan) - seen_plans):
        rejected.append({"plan_id": plan_id, "reason": "model_omitted_plan", "category": category})
    return accepted, rejected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate 100 Layer 1 query candidates from the locked Qdrant corpus."
    )
    parser.add_argument("--organization-id", default=os.getenv("SAVIRACORTEX_EVAL_ORGANIZATION_ID"))
    parser.add_argument("--seed", default="savira-layer1-v1")
    parser.add_argument("--max-context-chars", type=int, default=1800)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    load_environment()
    args = parse_args()
    if not args.organization_id:
        raise SystemExit("Set SAVIRACORTEX_EVAL_ORGANIZATION_ID or pass --organization-id.")
    try:
        organization_id = UUID(args.organization_id)
    except ValueError as exc:
        raise SystemExit("--organization-id must be a UUID.") from exc
    if args.max_context_chars < 200:
        raise SystemExit("--max-context-chars must be at least 200.")

    lock, catalogue = load_frozen_corpus()
    resources = configure_isolation()
    live_records = read_indexed_chunks(organization_id)
    records = validate_live_corpus(
        live_records, lock, catalogue, organization_id,
        resources["QDRANT_COLLECTION_NAME"],
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        grouped[item["document_version_id"]].append(item)
    if len(grouped) < 2:
        raise SystemExit("The locked corpus must contain at least two documents.")

    generator, model_name = build_generator()
    accepted, rejected = [], []
    for category, count in CATEGORY_COUNTS.items():
        plans = build_source_plans(
            records, category, count, args.seed, args.max_context_chars
        )
        LOG.info("Generating %d %s candidates.", count, category)
        try:
            good, bad = generate_category(generator, plans)
        except Exception as exc:
            LOG.exception("Generation failed for category %s.", category)
            good = []
            bad = [{
                "plan_id": plan["plan_id"],
                "category": category,
                "reason": "generation_call_failed",
                "error": f"{type(exc).__name__}: {exc}",
            } for plan in plans]
        accepted.extend(good)
        rejected.extend(bad)

    unique: dict[str, dict[str, Any]] = {}
    seen_queries: set[str] = set()
    for candidate in accepted:
        selected_ids = sorted(
            context["chunk_id"] for context in candidate["candidate_contexts"]
        )
        normalized_query = normalize_text(candidate["query"]).casefold()
        sample_id = "cand-" + sha256(
            "\n".join([normalized_query, *selected_ids])
        )[:16]
        if normalized_query in seen_queries:
            rejected.append({
                "query": candidate["query"],
                "reason": "duplicate_candidate_query",
                "category": candidate["category"],
            })
            continue
        seen_queries.add(normalized_query)

        unique[sample_id] = {
            "sample_id": sample_id,
            "query": candidate["query"],
            "ground_truth": None,
            "reference_answer": None,
            "candidate_source_chunks": [
                {
                    "chunk_id": context["chunk_id"],
                    "document_id": context["document_id"],
                    "document_version_id": context["document_version_id"],
                    "source_pdf": context["source_pdf"],
                    "page": context.get("page"),
                    "reference_context_candidate": next(
                        item["page_content"] for item in records
                        if item["chunk_id"] == context["chunk_id"]
                    ),
                    "relevance_grade": None,
                    "review_status": "pending",
                }
                for context in candidate["candidate_contexts"]
            ],
            "metadata": {
                "category": candidate["category"],
                "split": "test",
                "generation_plan_id": candidate["plan_id"],
                "review_status": "pending",
            },
        }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output.expanduser().resolve() if args.output else (
        ROOT / "evaluation" / "datasets" / f"synthetic_candidates_{run_id}.json"
    )
    total_requested = sum(CATEGORY_COUNTS.values())
    corpus_fingerprint_input = "\n".join(
        f"{item['chunk_id']}:{sha256(item['page_content'])}" for item in records
    )
    corpus_fingerprint = sha256(corpus_fingerprint_input)
    payload = {
        "dataset_id": "savira_layer1_retrieval_candidates",
        "dataset_version": "0.1.0",
        "dataset_status": "candidate_pending_human_review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation": {
            "engine": "langchain_openai.ChatOpenAI",
            "llm_model": model_name,
            "seed": args.seed,
            "max_context_chars_sent_to_model": args.max_context_chars,
            "category_distribution_status": "proposed_not_yet_approved",
            "requested_candidate_count": total_requested,
            "category_counts_requested": CATEGORY_COUNTS,
        },
        "corpus": {
            "organization_id": lock["organization_id"],
            "qdrant_collection": lock["qdrant_collection"],
            "corpus_lock": "evaluation/datasets/corpus_lock.json",
            "chunk_catalogue": "evaluation/datasets/chunk_catalogue.json",
            "chunk_count": len(records),
            "document_version_count": len(grouped),
            "source_pdfs": sorted({item["source_pdf"] for item in records}),
            "fingerprint_sha256": corpus_fingerprint,
        },
        "summary": {
            "requested_count": total_requested,
            "candidate_count": len(unique),
            "rejected_count": len(rejected),
            "complete": len(unique) == total_requested,
            "review_required": True,
        },
        "samples": list(unique.values()),
        "rejected_candidates": rejected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    LOG.info(
        "Wrote %d/%d candidates (%d rejected) to %s",
        len(unique), total_requested, len(rejected), output_path,
    )
    return 0 if len(unique) == total_requested else 2


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("EVALUATION_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(main())
