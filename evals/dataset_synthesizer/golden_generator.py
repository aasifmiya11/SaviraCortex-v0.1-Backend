"""Generate a per-PDF allocated DeepEval Golden dataset.

Run from the repository root:
    uv run python -m evals.dataset_synthesizer.golden_generator --overwrite
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from deepeval.synthesizer import Synthesizer
from deepeval.synthesizer.config import ContextConstructionConfig

from evals.dataset_synthesizer.custom_embeddings import SaviraDeepEvalEmbeddings
from evals.dataset_synthesizer.custom_llm import SaviraDeepEvalLLM
from evals.dataset_synthesizer.document_preprocessor import prepare_markdown_documents

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIRECTORY = (
    PROJECT_ROOT / "evals" / "dataset_synthesizer" / "corpus" / "source_pdfs"
)
DATASETS_DIRECTORY = PROJECT_ROOT / "evals" / "datasets"
TEMPORARY_DIRECTORY = PROJECT_ROOT / "evals" / "dataset_synthesizer" / ".tmp"
DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "evals" / "dataset_synthesizer" / "config" / "golden_allocation.json"
)
DEFAULT_DATASET_PATH = DATASETS_DIRECTORY / "synthetic_goldens.jsonl"
DEFAULT_METADATA_PATH = DATASETS_DIRECTORY / "metadata.json"

logger = logging.getLogger(__name__)


def _golden_to_dict(golden: Any) -> dict[str, Any]:
    """Serialize a DeepEval Golden without assuming a specific model version."""
    if hasattr(golden, "model_dump"):
        record = golden.model_dump(mode="json")
    elif hasattr(golden, "dict"):
        record = golden.dict()
    elif isinstance(golden, dict):
        record = dict(golden)
    else:
        record = vars(golden)

    if not isinstance(record, dict):
        raise TypeError(f"Unsupported Golden type: {type(golden).__name__}")

    for field in ("input", "expected_output", "context", "additional_metadata"):
        if field not in record and hasattr(golden, field):
            record[field] = getattr(golden, field)

    if not isinstance(record.get("input"), str) or not record["input"].strip():
        raise ValueError("DeepEval returned a Golden without a non-empty input.")
    if not record.get("expected_output"):
        raise ValueError("DeepEval returned a Golden without an expected_output.")
    if not isinstance(record.get("context"), list) or not record["context"]:
        raise ValueError("DeepEval returned a Golden without a non-empty context.")
    return record


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise FileNotFoundError(f"Golden allocation config not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("The allocation config must contain a JSON object.")
    return config


def _allocate_targets(
    manifests: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, int]:
    """Allocate the requested total proportionally to extracted text length.

    Per-document min/max values can be overridden in JSON. Allocation is
    deterministic and uses largest-remainder rounding while respecting caps.
    """
    global_config = config.get("global", {})
    documents_config = config.get("documents", {})

    minimum_total = int(global_config.get("minimum_total_goldens", 50))
    target_total = int(global_config.get("target_total_goldens", 55))
    maximum_total = int(global_config.get("maximum_total_goldens", 60))
    default_minimum = int(global_config.get("minimum_goldens_per_pdf", 3))
    default_maximum = int(global_config.get("maximum_goldens_per_pdf", 10))

    if not (1 <= minimum_total <= target_total <= maximum_total):
        raise ValueError(
            "Expected 1 <= minimum_total_goldens <= target_total_goldens "
            "<= maximum_total_goldens."
        )
    if default_minimum < 1 or default_maximum < default_minimum:
        raise ValueError("Invalid global per-PDF minimum/maximum.")

    names = [Path(item["source_pdf"]).name for item in manifests]
    if len(names) != len(set(names)):
        raise ValueError("Source PDF filenames must be unique.")

    minimums: dict[str, int] = {}
    maximums: dict[str, int] = {}
    fixed: dict[str, int] = {}
    weights: dict[str, int] = {}

    for item, name in zip(manifests, names):
        override = documents_config.get(name, {})
        minimum = int(override.get("min_goldens", default_minimum))
        maximum = int(override.get("max_goldens", default_maximum))
        if minimum < 1 or maximum < minimum:
            raise ValueError(f"Invalid allocation range for {name}: {minimum}..{maximum}")
        if "goldens" in override:
            exact = int(override["goldens"])
            if exact < minimum or exact > maximum:
                raise ValueError(
                    f"Exact allocation for {name} must be between {minimum} and {maximum}."
                )
            fixed[name] = exact
            minimum = maximum = exact
        minimums[name] = minimum
        maximums[name] = maximum
        weights[name] = max(1, int(item.get("extracted_character_count", 1)))

    capacity_min = sum(minimums.values())
    capacity_max = sum(maximums.values())
    if not capacity_min <= target_total <= capacity_max:
        raise ValueError(
            f"Target {target_total} cannot be allocated: document capacity is "
            f"{capacity_min}..{capacity_max}. Adjust the JSON allocation limits."
        )

    allocation = dict(minimums)
    remaining = target_total - sum(allocation.values())

    # Distribute in weighted rounds. Recompute weights after a document reaches
    # its maximum so the remaining quota flows to documents with spare capacity.
    while remaining > 0:
        active = [
            name for name in names if allocation[name] < maximums[name]
        ]
        if not active:
            raise RuntimeError("Allocation exhausted all per-document maximums.")
        total_weight = sum(weights[name] for name in active)
        quotas = {
            name: remaining * weights[name] / total_weight for name in active
        }
        added_this_round = 0

        for name in active:
            addition = min(
                maximums[name] - allocation[name],
                math.floor(quotas[name]),
            )
            if addition:
                allocation[name] += addition
                remaining -= addition
                added_this_round += addition

        if remaining == 0:
            break

        # Largest fractional remainders receive one each, in stable filename order.
        ranked = sorted(
            (name for name in active if allocation[name] < maximums[name]),
            key=lambda name: (-(quotas[name] % 1), name.lower()),
        )
        for name in ranked:
            if remaining == 0:
                break
            allocation[name] += 1
            remaining -= 1
            added_this_round += 1

        if added_this_round == 0:
            raise RuntimeError("Could not make progress allocating Golden targets.")

    if not minimum_total <= sum(allocation.values()) <= maximum_total:
        raise ValueError("Allocated total falls outside the configured global range.")
    return allocation


def _write_jsonl(records: list[dict[str, Any]], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, default=_json_default))
            file.write("\n")
    temporary_path.replace(output_path)
    return len(records)


def generate_dataset(
    pdf_paths: Iterable[str | Path],
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_path: str | Path = DEFAULT_DATASET_PATH,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Generate the configured number of Goldens from each source PDF."""
    pdf_paths = sorted(
        (Path(path).expanduser().resolve() for path in pdf_paths),
        key=lambda path: path.name.lower(),
    )
    if not pdf_paths:
        raise ValueError("No source PDFs were supplied.")
    if len({path.name for path in pdf_paths}) != len(pdf_paths):
        raise ValueError("Source PDF filenames must be unique.")

    for path in pdf_paths:
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise FileNotFoundError(f"Source PDF is missing or invalid: {path}")

    config_file = Path(config_path).expanduser().resolve()
    config = _load_config(config_file)

    # Explicitly exclude documents that are known to be too short to construct
    # useful contexts. Matching is by filename so the config remains portable.
    excluded_documents = set(config.get("excluded_documents", []))
    if any(not isinstance(name, str) or not name.strip() for name in excluded_documents):
        raise ValueError("excluded_documents must contain non-empty PDF filenames.")
    excluded_from_run = [
        str(path) for path in pdf_paths if path.name in excluded_documents
    ]
    pdf_paths = [path for path in pdf_paths if path.name not in excluded_documents]
    if not pdf_paths:
        raise ValueError("All supplied PDFs are excluded by golden_allocation.json.")

    dataset_file = Path(output_path).expanduser().resolve()
    metadata_file = Path(metadata_path).expanduser().resolve()
    if not overwrite and (dataset_file.exists() or metadata_file.exists()):
        raise FileExistsError(
            "Dataset or metadata already exists. Pass --overwrite to replace them."
        )

    context_settings = config.get("context", {})
    chunk_size = int(context_settings.get("chunk_size", 1000))
    chunk_overlap = int(context_settings.get("chunk_overlap", 200))
    min_context_length = int(context_settings.get("minimum_chunks_per_golden", 3))
    max_context_length = int(context_settings.get("maximum_chunks_per_golden", 30))
    max_concurrent = int(context_settings.get("max_concurrent", 10))

    if chunk_size < 1 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("Invalid chunk_size/chunk_overlap configuration.")
    if min_context_length < 1 or max_context_length < min_context_length:
        raise ValueError("Invalid minimum/maximum chunks per Golden.")
    if max_concurrent < 1:
        raise ValueError("max_concurrent must be at least 1.")

    TEMPORARY_DIRECTORY.mkdir(parents=True, exist_ok=True)
    markdown_paths, source_manifest = prepare_markdown_documents(
        pdf_paths, TEMPORARY_DIRECTORY
    )

    # Keep the original PDF name and extracted text size in the run manifest.
    for markdown_path, manifest in zip(markdown_paths, source_manifest):
        manifest["extracted_character_count"] = len(
            markdown_path.read_text(encoding="utf-8")
        )

    allocations = _allocate_targets(source_manifest, config)
    custom_llm = SaviraDeepEvalLLM()
    custom_embeddings = SaviraDeepEvalEmbeddings()
    all_records: list[dict[str, Any]] = []
    per_document_counts: dict[str, int] = {}
    failed_documents: list[dict[str, Any]] = []

    for markdown_path, manifest in zip(markdown_paths, source_manifest):
        source_name = Path(manifest["source_pdf"]).name
        target_count = allocations[source_name]
        logger.info(
            "Generating %d Goldens from %s (%s extracted characters).",
            target_count,
            source_name,
            manifest["extracted_character_count"],
        )

        # Isolate each PDF so its context quota cannot be consumed by another PDF.
        context_config = ContextConstructionConfig(
            critic_model=custom_llm,
            embedder=custom_embeddings,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_context_length=min_context_length,
            max_context_length=max_context_length,
            min_contexts_per_document=target_count,
            max_contexts_per_document=target_count,
        )
        synthesizer = Synthesizer(
            model=custom_llm,
            max_concurrent=max_concurrent,
        )
        try:
            generated = synthesizer.generate_goldens_from_docs(
                document_paths=[str(markdown_path)],
                include_expected_output=True,
                max_goldens_per_context=1,
                context_construction_config=context_config,
            )
            records = [_golden_to_dict(golden) for golden in generated]
        except Exception as exc:
            logger.exception(
                "Skipping %s after DeepEval Golden generation failed: %s",
                source_name,
                exc,
            )
            failed_documents.append(
                {
                    "source_pdf": source_name,
                    "requested": target_count,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        if len(records) != target_count:
            logger.warning(
                "%s: requested %d Goldens, but DeepEval generated %d; "
                "keeping the generated records and continuing.",
                source_name,
                target_count,
                len(records),
            )

        for record in records:
            record["source_pdf"] = source_name
            record["source_document_path"] = str(manifest["source_pdf"])
            context = record["context"]
            if not min_context_length <= len(context) <= max_context_length:
                raise RuntimeError(
                    f"{source_name}: a Golden has {len(context)} context chunks; "
                    f"expected {min_context_length}..{max_context_length}."
                )
        all_records.extend(records)
        per_document_counts[source_name] = len(records)

    if not all_records:
        raise RuntimeError(
            "DeepEval failed to generate any valid Goldens from the supplied PDFs."
        )

    count = _write_jsonl(all_records, dataset_file)
    expected_total = sum(allocations.values())
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "DeepEval Synthesizer.generate_goldens_from_docs (per-PDF)",
        "llm_model": custom_llm.get_model_name(),
        "embedding_model": custom_embeddings.get_model_name(),
        "source_documents": source_manifest,
        "excluded_documents": excluded_from_run,
        "allocation": {
            "target_total_goldens": expected_total,
            "per_document_targets": allocations,
            "per_document_generated": per_document_counts,
            "failed_documents": failed_documents,
        },
        "generation_config": {
            "config_file": str(config_file),
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "minimum_chunks_per_golden": min_context_length,
            "maximum_chunks_per_golden": max_context_length,
            "max_goldens_per_context": 1,
            "max_concurrent": max_concurrent,
        },
        "golden_count": count,
    }
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_temporary = metadata_file.with_suffix(metadata_file.suffix + ".tmp")
    metadata_temporary.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )
    metadata_temporary.replace(metadata_file)

    with dataset_file.open("r", encoding="utf-8") as file:
        persisted_count = sum(1 for line in file if line.strip())
    if persisted_count != count:
        raise RuntimeError(
            f"Dataset verification failed: expected {count}, found {persisted_count}."
        )

    # Only clean intermediate Markdown after generation and persistence succeed.
    for markdown_path in markdown_paths:
        markdown_path.unlink(missing_ok=True)
    try:
        TEMPORARY_DIRECTORY.rmdir()
    except OSError:
        pass

    logger.info("Saved %d Goldens to %s", count, dataset_file)
    logger.info("Saved metadata to %s", metadata_file)
    for name, generated_count in per_document_counts.items():
        logger.info("  %s: %d Goldens", name, generated_count)
    return dataset_file, metadata_file


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a per-PDF allocated SaviraCortex Golden dataset."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIRECTORY,
        help="Directory containing source PDFs.",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        type=Path,
        help="Specific PDF path; repeat to include multiple PDFs.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = _parse_args()

    if args.pdf:
        pdf_paths = args.pdf
    else:
        if not args.source_dir.is_dir():
            raise FileNotFoundError(f"PDF directory does not exist: {args.source_dir}")
        pdf_paths = sorted(args.source_dir.glob("*.pdf"))

    if not pdf_paths:
        raise FileNotFoundError(f"No PDF files found in {args.source_dir}.")

    generate_dataset(
        pdf_paths,
        config_path=args.config,
        output_path=args.output,
        metadata_path=args.metadata,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
