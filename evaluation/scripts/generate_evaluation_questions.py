"""Generate 1–3 structured query variants for each evidence-group candidate.

This is an evaluation-only data-preparation script. It reads the frozen chunk
catalogue, calls one reusable LLM agent once per candidate, and writes a new
candidate dataset. It never calls Qdrant or the production retrieval pipeline.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = logging.getLogger("evaluation.generate_questions")

CANDIDATES_PATH = (
    ROOT / "evaluation" / "datasets" / "evidence_group_candidates_20261104.json"
)
CATALOGUE_PATH = ROOT / "evaluation" / "datasets" / "chunk_catalogue.json"
CORPUS_LOCK_PATH = ROOT / "evaluation" / "datasets" / "corpus_lock.json"
OUTPUT_DIR = ROOT / "evaluation" / "datasets"


def load_environment() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required dataset file does not exist: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def validate_frozen_inputs() -> tuple[
    dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]
]:
    lock = read_json(CORPUS_LOCK_PATH)
    catalogue = read_json(CATALOGUE_PATH)
    source = read_json(CANDIDATES_PATH)

    if lock.get("status") != "locked_for_benchmark":
        raise RuntimeError("Corpus lock is not marked locked_for_benchmark.")
    if lock.get("full_text_status") != "verified_complete":
        raise RuntimeError("Frozen corpus full text is not verified complete.")
    if catalogue.get("catalogue_status") != "verified_complete":
        raise RuntimeError("Chunk catalogue is not marked verified_complete.")
    if source.get("dataset_status") != "candidate_pending_review":
        raise RuntimeError("Evidence-group input is not in candidate_pending_review state.")

    corpus = source.get("corpus")
    if not isinstance(corpus, dict):
        raise RuntimeError("Evidence-group dataset has no corpus metadata.")
    if corpus.get("organization_id") != lock.get("organization_id"):
        raise RuntimeError("Evidence-group organization does not match corpus lock.")
    if corpus.get("qdrant_collection") != lock.get("qdrant_collection"):
        raise RuntimeError("Evidence-group collection does not match corpus lock.")

    chunks = catalogue.get("chunks")
    if not isinstance(chunks, list):
        raise RuntimeError("Chunk catalogue has no chunks array.")
    chunk_by_id: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise RuntimeError("Chunk catalogue contains a malformed chunk record.")
        chunk_id = chunk.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise RuntimeError("Chunk catalogue contains a chunk without chunk_id.")
        if chunk_id in chunk_by_id:
            raise RuntimeError(f"Duplicate chunk ID in catalogue: {chunk_id}")
        if not isinstance(chunk.get("chunk_text"), str) or not chunk["chunk_text"].strip():
            raise RuntimeError(f"Chunk text is missing for {chunk_id}.")
        chunk_by_id[chunk_id] = chunk

    locked_versions = {
        item["document_version_id"] for item in lock.get("source_documents", [])
    }
    locked_chunks = [
        chunk for chunk in chunks
        if chunk.get("document_version_id") in locked_versions
    ]
    if len(locked_chunks) != lock.get("qdrant_point_count"):
        raise RuntimeError(
            "Locked chunk count does not match corpus_lock.json "
            f"({len(locked_chunks)} != {lock.get('qdrant_point_count')})."
        )

    candidates = source.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Evidence-group dataset has no candidates array.")
    if len(candidates) != source.get("preparation_contract", {}).get("candidate_count"):
        raise RuntimeError("Candidate count does not match the preparation contract.")

    seen_candidate_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise RuntimeError("Evidence-group dataset contains a malformed candidate.")
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise RuntimeError("Candidate is missing candidate_id.")
        if candidate_id in seen_candidate_ids:
            raise RuntimeError(f"Duplicate candidate ID: {candidate_id}")
        seen_candidate_ids.add(candidate_id)

        evidence_group = candidate.get("evidence_group")
        if not isinstance(evidence_group, list) or not 3 <= len(evidence_group) <= 10:
            raise RuntimeError(
                f"{candidate_id} must contain between 3 and 10 evidence chunks."
            )
        seen_chunk_ids: set[str] = set()
        for reference in evidence_group:
            if not isinstance(reference, dict):
                raise RuntimeError(f"{candidate_id} contains a malformed chunk reference.")
            chunk_id = reference.get("chunk_id")
            if not isinstance(chunk_id, str) or chunk_id in seen_chunk_ids:
                raise RuntimeError(f"{candidate_id} has a missing or duplicate chunk ID.")
            seen_chunk_ids.add(chunk_id)
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                raise RuntimeError(f"{candidate_id} references unknown chunk {chunk_id}.")
            for field in ("document_id", "document_version_id", "source_filename"):
                if reference.get(field) != chunk.get(field):
                    raise RuntimeError(
                        f"{candidate_id} metadata mismatch for {chunk_id}: {field}."
                    )
            if chunk.get("document_version_id") not in locked_versions:
                raise RuntimeError(f"{candidate_id} references an unlocked document version.")

        seed_ids = candidate.get("seed_evidence_chunk_ids")
        if not isinstance(seed_ids, list) or not seed_ids:
            raise RuntimeError(f"{candidate_id} has no seed evidence chunk IDs.")
        if any(seed_id not in seen_chunk_ids for seed_id in seed_ids):
            raise RuntimeError(f"{candidate_id} seed evidence is not a subset of its group.")

        context = candidate.get("conversation_context")
        if not isinstance(context, list) or len(context) > 6 or len(context) % 2:
            raise RuntimeError(
                f"{candidate_id} conversation context must contain 0–3 complete exchanges."
            )
        for index, message in enumerate(context):
            expected_role = "user" if index % 2 == 0 else "assistant"
            if (
                not isinstance(message, dict)
                or message.get("role") != expected_role
                or not isinstance(message.get("content"), str)
                or not message["content"].strip()
            ):
                raise RuntimeError(
                    f"{candidate_id} conversation context must alternate "
                    "non-empty user and assistant messages."
                )

    return source, candidates, chunk_by_id


def build_evidence_chunks(
    candidate: dict[str, Any],
    chunk_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve candidate chunk references to full text from the frozen catalogue."""
    resolved = []
    for reference in candidate["evidence_group"]:
        chunk = chunk_by_id[reference["chunk_id"]]
        resolved.append({
            "chunk_id": chunk["chunk_id"],
            "document_id": chunk["document_id"],
            "document_version_id": chunk["document_version_id"],
            "source_filename": chunk["source_filename"],
            "page": chunk.get("page"),
            "selection_role": reference.get("selection_role"),
            "text": chunk["chunk_text"],
        })
    return resolved


def write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate up to three structured question variants per frozen "
            "evidence-group candidate."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=CANDIDATES_PATH,
        help="Evidence-group candidate JSON (default: the curated 100-candidate file).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: a new timestamped file in evaluation/datasets).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N candidates (useful for a small live smoke test).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate all frozen inputs and references without making an LLM call.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing the explicitly supplied output path.",
    )
    return parser.parse_args()


def main() -> int:
    load_environment()
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1.")

    global CANDIDATES_PATH
    CANDIDATES_PATH = args.input.expanduser().resolve()

    source, all_candidates, chunk_by_id = validate_frozen_inputs()
    candidates = all_candidates[: args.limit] if args.limit else all_candidates
    LOG.info(
        "Validated %d evidence-group candidates against %d frozen catalogue chunks.",
        len(all_candidates),
        len(chunk_by_id),
    )
    if args.validate_only:
        LOG.info("Validation-only run complete; no LLM client was created.")
        return 0

    from evaluation.agent import QuestionGenerationAgent

    # Construct one reusable client/structured-output agent for the whole run.
    agent = QuestionGenerationAgent()
    generated_records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    total_variants = 0

    for index, candidate in enumerate(candidates, start=1):
        candidate_id = candidate["candidate_id"]
        context = candidate["conversation_context"]
        evidence_chunks = build_evidence_chunks(candidate, chunk_by_id)
        LOG.info(
            "[%d/%d] Generating question variants for %s (%d context messages, %d chunks).",
            index,
            len(candidates),
            candidate_id,
            len(context),
            len(evidence_chunks),
        )
        try:
            result = agent.generate(
                candidate_id=candidate_id,
                context=context,
                retrieved_chunks=evidence_chunks,
            )
            for variant_index, generated in enumerate(result.questions, start=1):
                question_id = f"Q-{candidate_id}-{variant_index:02d}"
                generated_records.append({
                    "question_id": question_id,
                    "question": {
                        "text": generated.question,
                        "style": generated.style,
                        "context_dependency": generated.context_dependency,
                        "generation_rationale": generated.generation_rationale,
                    },
                    "context": context,
                    "retrieved_chunks": evidence_chunks,
                    "provenance": {
                        "candidate_id": candidate_id,
                        "source_candidate_id": candidate.get("source_candidate_id"),
                        "evidence_pattern": candidate.get("evidence_pattern"),
                        "seed_evidence_chunk_ids": candidate["seed_evidence_chunk_ids"],
                        "selection_status": candidate.get("status"),
                    },
                    "review_status": "pending_human_review",
                })
            total_variants += len(result.questions)
        except Exception as exc:
            LOG.exception("Question generation failed for %s.", candidate_id)
            failures.append({
                "candidate_id": candidate_id,
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
            })

    generated_at = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else OUTPUT_DIR / f"generated_questions_{run_id}.json"
    )
    if output_path.exists() and not args.overwrite:
        raise SystemExit(
            f"Output already exists: {output_path}. Choose another --output "
            "or pass --overwrite explicitly."
        )

    expected_candidate_count = len(candidates)
    complete = len(failures) == 0 and len(generated_records) >= expected_candidate_count
    payload = {
        "dataset_id": "savira_retrieval_question_variants",
        "schema_version": "1.0",
        "dataset_status": (
            "candidate_pending_human_review" if complete else "generation_incomplete"
        ),
        "generated_at": generated_at,
        "generation": {
            "agent": "evaluation.agent.question_generation_agent.QuestionGenerationAgent",
            "structured_output_schema": "QuestionGenerationOutput",
            "llm_provider_client": "langchain_openai.ChatOpenAI",
            "llm_model": agent.model_name,
            "calls_per_candidate": 1,
            "minimum_questions_per_successful_candidate": 1,
            "maximum_questions_per_candidate": 3,
            "requested_candidate_count": expected_candidate_count,
            "successful_candidate_count": expected_candidate_count - len(failures),
            "failed_candidate_count": len(failures),
            "generated_question_count": len(generated_records),
            "conversation_context_included": True,
            "source_chunk_text_loaded_from": "evaluation/datasets/chunk_catalogue.json",
            "note": (
                "retrieved_chunks contains the curated evidence-group chunks "
                "provided to the generator. It does not contain production "
                "retriever results."
            ),
        },
        "corpus": source.get("corpus"),
        "source_dataset": str(args.input),
        "summary": {
            "candidate_count": expected_candidate_count,
            "question_count": len(generated_records),
            "minimum_possible_questions": expected_candidate_count,
            "maximum_possible_questions": expected_candidate_count * 3,
            "failed_candidates": len(failures),
            "complete": complete,
            "human_review_required": True,
            "reference_answers_generated": False,
            "relevance_grades_assigned": False,
        },
        "questions": generated_records,
        "generation_failures": failures,
    }
    write_json_atomically(output_path, payload)
    LOG.info(
        "Wrote %d question variants from %d/%d candidates (%d failures) to %s.",
        len(generated_records),
        expected_candidate_count - len(failures),
        expected_candidate_count,
        len(failures),
        output_path,
    )
    return 0 if complete else 2


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("EVALUATION_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(main())
