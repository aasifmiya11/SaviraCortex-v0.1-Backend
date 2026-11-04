"""Generate RAGAS candidates from the exact chunks indexed by SaviraCortex."""
from __future__ import annotations
import argparse, hashlib, json, logging, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOG = logging.getLogger("evaluation.generate")


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


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
            scroll_filter=query_filter, limit=256, offset=offset,
            with_payload=True, with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            metadata = payload.get("metadata")
            content = payload.get("page_content")
            if not isinstance(metadata, dict) or not isinstance(content, str):
                continue
            status = metadata.get("status", payload.get("status"))
            if status not in {"active", "superseded"}:
                continue
            doc_id = metadata.get("document_id")
            version_id = metadata.get("document_version_id")
            chunk_index = metadata.get("chunk_index")
            if doc_id is None or version_id is None or chunk_index is None:
                LOG.warning("Skipping point %s with incomplete identity.", point.id)
                continue
            records.append({
                "qdrant_point_id": str(point.id),
                "page_content": content,
                "metadata": dict(metadata),
                "chunk_id": f"{version_id}:{chunk_index}",
                "document_id": str(doc_id),
                "document_version_id": str(version_id),
                "chunk_index": int(chunk_index),
                "source_pdf": str(metadata.get("source") or "unknown"),
                "page": metadata.get("page"),
                "status": status,
            })
        if offset is None:
            break
    records.sort(key=lambda x: (x["document_version_id"], x["chunk_index"]))
    return records


def build_generator():
    from langchain_openai import ChatOpenAI
    from ragas.testset import TestsetGenerator
    from app.core.config import settings
    from app.rag.embeddings.huggingface_embeddings import embedding_client

    if not settings.OPENAI_API_KEY or not settings.OPENAI_MODEL:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_MODEL are required.")
    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL, api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL, temperature=0.2,
    )
    return TestsetGenerator.from_langchain(
        llm=llm, embedding_model=embedding_client.get_embedding_model()
    )


def map_contexts(
    contexts: list[str],
    chunks_by_text: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    matched: dict[str, dict[str, Any]] = {}
    unmatched: list[str] = []
    for context in contexts:
        candidates = chunks_by_text.get(normalize_text(context), [])
        if not candidates:
            unmatched.append(context)
        for candidate in candidates:
            matched[candidate["chunk_id"]] = candidate
    return list(matched.values()), unmatched


def generate_group(
    generator: Any,
    records: list[dict[str, Any]],
    requested_count: int,
    scope: str,
    chunks_by_text: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from langchain_core.documents import Document

    documents = [
        Document(
            page_content=item["page_content"],
            metadata={
                **item["metadata"],
                "evaluation_chunk_id": item["chunk_id"],
                "evaluation_qdrant_point_id": item["qdrant_point_id"],
            },
        )
        for item in records
    ]
    testset = generator.generate_with_chunks(
        chunks=documents, testset_size=requested_count,
        raise_exceptions=False,
    )
    accepted, rejected = [], []
    for row in testset.to_pandas().to_dict(orient="records"):
        query = str(row.get("user_input") or "").strip()
        answer = str(row.get("reference") or "").strip()
        raw_contexts = row.get("reference_contexts")
        if isinstance(raw_contexts, str):
            raw_contexts = [raw_contexts]
        elif raw_contexts is None:
            raw_contexts = []
        else:
            raw_contexts = list(raw_contexts)
        contexts = [
            str(value).strip() for value in raw_contexts
            if isinstance(value, str) and value.strip()
        ]
        if not query or not answer or not contexts:
            rejected.append({"query": query, "reason": "missing_query_answer_or_context", "scope": scope})
            continue
        mapped, unmatched = map_contexts(contexts, chunks_by_text)
        if unmatched or not mapped:
            rejected.append({
                "query": query,
                "reason": "reference_context_not_exactly_mapped_to_indexed_chunk",
                "unmatched_context_count": len(unmatched),
                "scope": scope,
            })
            continue

        doc_ids = sorted({item["document_id"] for item in mapped})
        relevant_chunks = [{
            "chunk_id": item["chunk_id"],
            "document_id": item["document_id"],
            "document_version_id": item["document_version_id"],
            "chunk_index": item["chunk_index"],
            "source_pdf": item["source_pdf"],
            "page": item["page"],
            "relevance_grade": 3,
        } for item in sorted(mapped, key=lambda x: (x["document_version_id"], x["chunk_index"]))]
        key = "\n".join([normalize_text(query).lower(), *sorted(x["chunk_id"] for x in mapped)])
        accepted.append({
            "sample_id": "syn-" + sha256(key)[:16],
            "query": query,
            "reference_answer": answer,
            "reference_contexts": contexts,
            "relevant_documents": doc_ids,
            "relevant_chunks": relevant_chunks,
            "metadata": {
                "generation_scope": scope,
                "question_type": "cross_document" if len(doc_ids) > 1 else "single_document",
                "synthesizer": str(row.get("synthesizer_name") or "ragas"),
                "source_pdfs": sorted({item["source_pdf"] for item in mapped}),
                "review_status": "pending",
            },
        })
    return accepted, rejected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate candidate questions from indexed evaluation chunks."
    )
    parser.add_argument("--organization-id", default=os.getenv("SAVIRACORTEX_EVAL_ORGANIZATION_ID"))
    parser.add_argument("--questions-per-pdf", type=int, default=10)
    parser.add_argument("--cross-document-questions", type=int, default=20)
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
    if args.questions_per_pdf < 0 or args.cross_document_questions < 0:
        raise SystemExit("Question counts cannot be negative.")

    resources = configure_isolation()
    records = read_indexed_chunks(organization_id)
    if not records:
        raise SystemExit("No eligible indexed chunks found; ingest the corpus first.")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        groups[item["document_version_id"]].append(item)
    chunks_by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        chunks_by_text[normalize_text(item["page_content"])].append(item)

    generator = build_generator()
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for version_id, group in sorted(groups.items()):
        if args.questions_per_pdf == 0:
            break
        LOG.info("Generating %d questions for %s", args.questions_per_pdf, group[0]["source_pdf"])
        group_chunks_by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in group:
            group_chunks_by_text[normalize_text(item["page_content"])].append(item)
        good, bad = generate_group(
            generator, group, args.questions_per_pdf,
            f"document:{version_id}", group_chunks_by_text,
        )
        accepted.extend(good)
        rejected.extend(bad)

    if args.cross_document_questions and len(groups) > 1:
        LOG.info("Generating %d corpus-wide questions", args.cross_document_questions)
        good, bad = generate_group(
            generator, records, args.cross_document_questions,
            "corpus", chunks_by_text,
        )
        accepted.extend(good)
        rejected.extend(bad)

    unique: dict[str, dict[str, Any]] = {}
    for sample in accepted:
        unique.setdefault(sample["sample_id"], sample)
    accepted = list(unique.values())
    fingerprint = "\n".join(
        f'{item["chunk_id"]}:{sha256(item["page_content"])}' for item in records
    )
    try:
        import ragas
        ragas_version = getattr(ragas, "__version__", "unknown")
    except Exception:
        ragas_version = "unknown"

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output.expanduser().resolve() if args.output else (
        ROOT / "evaluation" / "datasets" / f"synthetic_candidates_{run_id}.json"
    )
    payload = {
        "dataset_name": "SaviraCortex synthetic retrieval benchmark candidates",
        "schema_version": "1.0",
        "dataset_status": "candidate_pending_review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation": {
            "engine": "ragas",
            "ragas_version": ragas_version,
            "llm_model": os.getenv("OPENAI_MODEL"),
            "questions_per_pdf_requested": args.questions_per_pdf,
            "cross_document_questions_requested": args.cross_document_questions,
        },
        "corpus": {
            "organization_id": str(organization_id),
            "qdrant_collection": resources["QDRANT_COLLECTION_NAME"],
            "chunk_count": len(records),
            "document_version_count": len(groups),
            "source_pdfs": sorted({item["source_pdf"] for item in records}),
            "fingerprint_sha256": sha256(fingerprint),
            "eligible_version_statuses": ["active", "superseded"],
        },
        "summary": {
            "candidate_count": len(accepted),
            "rejected_count": len(rejected),
            "cross_document_count": sum(
                item["metadata"]["question_type"] == "cross_document"
                for item in accepted
            ),
        },
        "samples": accepted,
        "rejected_candidates": rejected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    LOG.info("Wrote %d candidates and %d rejected rows to %s", len(accepted), len(rejected), output_path)
    return 0 if accepted else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("EVALUATION_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(main())
