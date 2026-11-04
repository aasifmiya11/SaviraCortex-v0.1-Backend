"""Run the SaviraCortex document ingestion and indexing services on the evaluation corpus."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = logging.getLogger("evaluation.ingest")
EXCLUDED_FILENAMES = {"Sajid_Miya_AI_Engineer_resume.pdf"}


def _load_environment() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")


def _configure_evaluation_isolation() -> dict[str, str]:
    # .env is loaded before this function. App service singletons are imported
    # only after the evaluation values replace the production settings.
    from app.core.config import settings

    required = {
        "SAVIRACORTEX_EVAL_QDRANT_COLLECTION": (
            "QDRANT_COLLECTION_NAME",
            settings.EVAL_QDRANT_COLLECTION_NAME,
        ),
        "SAVIRACORTEX_EVAL_QDRANT_SUMMARY_COLLECTION": (
            "QDRANT_SUMMARY_COLLECTION_NAME",
            settings.EVAL_QDRANT_SUMMARY_COLLECTION_NAME,
        ),
        "SAVIRACORTEX_EVAL_B2_STORAGE_PREFIX": (
            "B2_STORAGE_PREFIX",
            settings.EVAL_B2_STORAGE_PREFIX,
        ),
    }
    missing = [key for key, (_, value) in required.items() if not value or not value.strip()]
    if missing:
        raise RuntimeError("Missing evaluation isolation settings: " + ", ".join(missing))

    production_values = {
        "QDRANT_COLLECTION_NAME": settings.QDRANT_COLLECTION_NAME,
        "QDRANT_SUMMARY_COLLECTION_NAME": settings.QDRANT_SUMMARY_COLLECTION_NAME,
        "B2_STORAGE_PREFIX": settings.B2_STORAGE_PREFIX,
    }
    evaluation_values = {
        app_key: value.strip()
        for app_key, value in required.values()
    }
    for app_key, evaluation_value in evaluation_values.items():
        production_value = production_values.get(app_key)
        if production_value and evaluation_value == production_value:
            raise RuntimeError(
                f"{app_key} points to the production/default resource; choose an isolated evaluation resource."
            )

    os.environ.update(evaluation_values)
    settings.QDRANT_COLLECTION_NAME = evaluation_values["QDRANT_COLLECTION_NAME"]
    settings.QDRANT_SUMMARY_COLLECTION_NAME = evaluation_values["QDRANT_SUMMARY_COLLECTION_NAME"]
    settings.B2_STORAGE_PREFIX = evaluation_values["B2_STORAGE_PREFIX"]
    return evaluation_values


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register and index approved evaluation PDFs."
    )
    parser.add_argument(
        "--organization-id",
        default=os.getenv("SAVIRACORTEX_EVAL_ORGANIZATION_ID"),
        help="Existing evaluation organization UUID (or SAVIRACORTEX_EVAL_ORGANIZATION_ID).",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT / "evaluation" / "corpus" / "source_pdfs",
    )
    parser.add_argument(
        "--allow-resume",
        action="store_true",
        help="Include the resume PDF (excluded by default).",
    )
    return parser.parse_args()


def main() -> int:
    _load_environment()
    args = _parse_args()
    if not args.organization_id:
        raise SystemExit("Provide --organization-id or SAVIRACORTEX_EVAL_ORGANIZATION_ID.")
    try:
        organization_id = UUID(args.organization_id)
    except ValueError as exc:
        raise SystemExit("--organization-id must be a valid UUID.") from exc

    resources = _configure_evaluation_isolation()

    # App modules create Qdrant/storage singletons at import time. Set the
    # evaluation collection names and B2 prefix before importing those modules.
    from app.services.document_ingestion import DocumentIngestionService
    from app.services.document_indexing.indexing_orchestrator import (
        DocumentIndexingOrchestrator,
    )

    source_dir = args.source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"PDF source directory does not exist: {source_dir}")
    pdf_paths = sorted(
        p for p in source_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )
    if not args.allow_resume:
        pdf_paths = [p for p in pdf_paths if p.name not in EXCLUDED_FILENAMES]
    if not pdf_paths:
        raise SystemExit(f"No eligible PDFs found in {source_dir}")

    ingestion_service = DocumentIngestionService()
    indexing_orchestrator = DocumentIndexingOrchestrator()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = ROOT / "evaluation" / "results" / f"ingestion_{run_id}.json"
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": str(organization_id),
        "source_directory": str(source_dir),
        "resources": resources,
        "documents": [],
        "status": "running",
    }
    _write_manifest(manifest_path, manifest)

    failed = False
    review_required = False
    for pdf_path in pdf_paths:
        LOG.info("Processing %s", pdf_path.name)
        record: dict[str, Any] = {"filename": pdf_path.name, "status": "started"}
        manifest["documents"].append(record)
        _write_manifest(manifest_path, manifest)
        try:
            result = ingestion_service.ingest_pdf(
                pdf_path, organization_id=organization_id
            )
            record["ingestion_status"] = result.status
            record["page_count"] = result.page_count
            record["validation_warnings"] = list(result.validation_warnings)

            if result.status == "duplicate":
                record["status"] = "duplicate_skipped"
                LOG.warning("Skipping existing duplicate: %s", pdf_path.name)
            elif result.status == "review_required":
                record["status"] = "review_required"
                review_required = True
                LOG.warning("Duplicate review required; not indexing %s", pdf_path.name)
            elif result.status == "registered_pending":
                registration = result.registration_result
                if registration is None:
                    raise RuntimeError("Pending ingestion has no registration result.")
                indexed = indexing_orchestrator.index_pending_version(
                    registration.document_version_id,
                    organization_id=organization_id,
                )
                record.update({
                    "document_id": str(indexed.document_id),
                    "document_version_id": str(indexed.document_version_id),
                    "version_number": indexed.version_number,
                    "indexed_page_count": indexed.page_count,
                    "ocr_page_count": indexed.ocr_page_count,
                    "chunk_count": indexed.chunk_count,
                    "qdrant_point_ids": indexed.qdrant_point_ids,
                    "status": indexed.status,
                    "summary_sync_pending": indexed.summary_sync_pending,
                    "lifecycle_sync_pending": indexed.lifecycle_sync_pending,
                    "sync_errors": indexed.sync_errors,
                })
                LOG.info(
                    "%s indexed: %d pages, %d OCR pages, %d chunks",
                    pdf_path.name, indexed.page_count,
                    indexed.ocr_page_count, indexed.chunk_count,
                )
            else:
                raise RuntimeError(f"Unexpected ingestion status: {result.status!r}")
        except Exception as exc:
            record.update({
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            failed = True
            LOG.exception("Failed processing %s; stopping this run.", pdf_path.name)
            _write_manifest(manifest_path, manifest)
            break
        _write_manifest(manifest_path, manifest)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["status"] = (
        "failed" if failed else
        "review_required" if review_required else
        "completed"
    )
    _write_manifest(manifest_path, manifest)
    LOG.info("Ingestion manifest written to %s", manifest_path)
    return 1 if failed else 2 if review_required else 0


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("EVALUATION_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(main())
