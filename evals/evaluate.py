"""Evaluate the real production SaviraCortex LangGraph RAG workflow.

Run from the repository root:
    uv run python -m evals.evaluate --organization-id <UUID> --user-id <UUID>

Every Golden is passed through create_rag_graph(...).ainvoke(). DeepEval
retrieval_context is taken from the exact context_documents/retrieved_documents
view consumed by the production Generation node, not from Golden.context.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import UUID

from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
)
from deepeval.test_case import LLMTestCase
from sqlalchemy.orm import Session

from app.agents.Generation import GenerationAgent
from app.agents.Multi_query_generator import MultiQueryGeneratorAgent
from app.core.config import settings
from app.core.database import get_db_session
from app.validation import StaticValidationLayer
from evals.dataset_synthesizer.custom_llm import SaviraDeepEvalLLM

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "evals" / "datasets" / "synthetic_goldens.jsonl"
DEFAULT_RESULTS_DIRECTORY = PROJECT_ROOT / "evals" / "results"
logger = logging.getLogger(__name__)


def load_goldens(dataset_path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Golden dataset not found: {dataset_path}")

    records: list[dict[str, Any]] = []
    with dataset_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record.get("input"), str) or not record["input"].strip():
                raise ValueError(f"Golden line {line_number} has no valid input.")
            if not isinstance(record.get("expected_output"), str) or not record["expected_output"].strip():
                raise ValueError(f"Golden line {line_number} has no valid expected_output.")
            records.append(record)
            if limit is not None and len(records) >= limit:
                break

    if not records:
        raise ValueError("The Golden dataset is empty.")
    return records


def build_metrics(model: SaviraDeepEvalLLM) -> list[Any]:
    return [
        AnswerRelevancyMetric(model=model, include_reason=True),
        FaithfulnessMetric(model=model, include_reason=True),
        ContextualPrecisionMetric(model=model, include_reason=True),
        ContextualRecallMetric(model=model, include_reason=True),
        ContextualRelevancyMetric(model=model, include_reason=True),
    ]


def _answer_text(generation_output: Any) -> str:
    return "\r\n\r\n".join(
        segment.text for segment in generation_output.segments
    ).strip()


def _build_production_graph(
    *,
    db: Session,
    chunk_collection_name: str,
    summary_collection_name: str,
):
    """Compose production services against isolated evaluation collections.

    Several production vector-store modules expose module-level singleton
    clients. Set their configured collection names before importing those
    modules so their import-time initialization also targets evaluation
    collections, never production collections.
    """
    settings.QDRANT_COLLECTION_NAME = chunk_collection_name
    settings.QDRANT_SUMMARY_COLLECTION_NAME = summary_collection_name

    from app.rag.retrieval.adaptive_k_selector import AdaptiveKSelector
    from app.rag.retrieval.candidate_document_generator import CandidateDocumentGenerator
    from app.rag.retrieval.cross_encoder_reranker import CrossEncoderReranker
    from app.rag.retrieval.dense import DenseRetriever
    from app.rag.retrieval.global_fusion import GlobalResultFusion
    from app.rag.retrieval.pipeline import HybridRetrievalPipeline
    from app.rag.retrieval.qdrant_bm25 import QdrantBM25Retriever
    from app.rag.vector_stores.qdrant import QdrantVectorStoreClient
    from app.rag.vector_stores.qdrant_summary import QdrantSummaryStore
    from app.repositories.authorization_repository import AuthorizationRepository
    from app.services.authorization.authorization_service import AuthorizationService
    from app.services.retrieval.retrieval_service import RetrievalOrchestrator
    from app.workflows.rag.graph import create_rag_graph

    chunk_store = QdrantVectorStoreClient(collection_name=chunk_collection_name)
    summary_store = QdrantSummaryStore(collection_name=summary_collection_name)

    hybrid_pipeline = HybridRetrievalPipeline(
        dense_retriever=DenseRetriever(vector_store=chunk_store),
        bm25_retriever=QdrantBM25Retriever(vector_store=chunk_store),
    )
    retrieval_orchestrator = RetrievalOrchestrator(
        authorization_service=AuthorizationService(
            repository=AuthorizationRepository(db)
        ),
        multi_query_agent=MultiQueryGeneratorAgent(),
        candidate_document_generator=CandidateDocumentGenerator(
            summary_store=summary_store
        ),
        hybrid_retrieval_pipeline=hybrid_pipeline,
        global_fusion=GlobalResultFusion(),
        cross_encoder_reranker=CrossEncoderReranker(),
        adaptive_k_selector=AdaptiveKSelector(),
    )

    return create_rag_graph(
        retriever=retrieval_orchestrator,
        generation_agent=GenerationAgent(),
        validator=StaticValidationLayer(),
    )


async def evaluate_dataset(
    *,
    organization_id: UUID,
    user_id: UUID,
    chunk_collection_name: str,
    summary_collection_name: str,
    dataset_path: Path = DEFAULT_DATASET,
    limit: int | None = None,
) -> dict[str, Any]:
    if (
        not chunk_collection_name
        or chunk_collection_name == settings.QDRANT_COLLECTION_NAME
    ):
        raise ValueError("Evaluation must never use the production chunk collection.")
    if (
        not summary_collection_name
        or summary_collection_name == settings.QDRANT_SUMMARY_COLLECTION_NAME
    ):
        raise ValueError("Evaluation must never use the production summary collection.")

    goldens = load_goldens(dataset_path, limit=limit)
    judge_model = SaviraDeepEvalLLM()
    metrics = build_metrics(judge_model)
    per_golden: list[dict[str, Any]] = []

    # Keep the request-scoped SQLAlchemy session on this thread while the
    # async graph invokes the synchronous authorization repository.
    with get_db_session() as db:
        graph = _build_production_graph(
            db=db,
            chunk_collection_name=chunk_collection_name,
            summary_collection_name=summary_collection_name,
        )

        for index, golden in enumerate(goldens, start=1):
            query = golden["input"]
            state = await graph.ainvoke(
                {
                    "query": query,
                    "organization_id": organization_id,
                    "user_id": user_id,
                },
                config={"recursion_limit": 100},
            )

            generation_output = state.get("generation_output")
            if generation_output is None:
                raise RuntimeError(
                    f"Production RAG graph did not generate an answer for "
                    f"Golden {index}. Validation error: "
                    f"{state.get('validation_error')}; graph errors: "
                    f"{state.get('errors')}"
                )

            # This is the exact ordered evidence view passed to GenerationAgent.
            generation_documents = state.get("retrieved_documents") or []
            retrieval_context = [
                item["page_content"]
                for item in generation_documents
                if isinstance(item, dict)
                and isinstance(item.get("page_content"), str)
                and item["page_content"].strip()
            ]
            actual_output = _answer_text(generation_output)

            test_case = LLMTestCase(
                input=query,
                actual_output=actual_output,
                expected_output=golden["expected_output"],
                retrieval_context=retrieval_context,
            )

            metric_results: dict[str, Any] = {}
            for metric in metrics:
                metric_name = metric.__class__.__name__
                try:
                    metric.measure(test_case)
                    metric_results[metric_name] = {
                        "score": metric.score,
                        "success": metric.is_successful(),
                        "reason": metric.reason,
                    }
                except Exception as exc:
                    logger.exception(
                        "Metric %s failed for Golden %d.",
                        metric_name,
                        index,
                    )
                    metric_results[metric_name] = {
                        "score": None,
                        "success": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                    }

            validation_result = state.get("validation_result")
            per_golden.append(
                {
                    "golden_index": index,
                    "source_pdf": golden.get("source_pdf"),
                    "input": query,
                    "expected_output": golden["expected_output"],
                    "actual_output": actual_output,
                    "retrieved_chunk_count": len(retrieval_context),
                    "generation_context": generation_documents,
                    "original_retrieved_documents": state.get("retrieved_documents") or [],
                    "generation_output": generation_output.model_dump(mode="json"),
                    "workflow": {
                        "retrieval_attempt": state.get("retrieval_attempt", 0),
                        "retrieval_diagnostics": state.get("retrieval_diagnostics"),
                        "validation_result": (
                            validation_result.model_dump(mode="json")
                            if validation_result is not None
                            else None
                        ),
                        "errors": state.get("errors") or [],
                    },
                    "metrics": metric_results,
                }
            )
            logger.info(
                "Evaluated Golden %d/%d (%s) through production LangGraph.",
                index,
                len(goldens),
                golden.get("source_pdf", "unknown source"),
            )

    metric_names = [metric.__class__.__name__ for metric in metrics]
    summary: dict[str, Any] = {}
    for metric_name in metric_names:
        scores = [
            item["metrics"][metric_name]["score"]
            for item in per_golden
            if isinstance(item["metrics"][metric_name].get("score"), (int, float))
        ]
        summary[metric_name] = {
            "mean_score": mean(scores) if scores else None,
            "scored_cases": len(scores),
            "total_cases": len(per_golden),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "golden_count": len(goldens),
        "organization_id": str(organization_id),
        "user_id": str(user_id),
        "qdrant_chunk_collection": chunk_collection_name,
        "qdrant_summary_collection": summary_collection_name,
        "orchestrator": "production RetrievalOrchestrator + production LangGraph RAG workflow",
        "summary": summary,
        "results": per_golden,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the production SaviraCortex LangGraph RAG workflow."
    )
    parser.add_argument("--organization-id", default=settings.EVAL_ORGANIZATION_ID)
    parser.add_argument("--user-id", default=settings.EVAL_USER_ID)
    parser.add_argument("--collection", default=settings.EVAL_QDRANT_COLLECTION_NAME)
    parser.add_argument(
        "--summary-collection",
        default=settings.EVAL_QDRANT_SUMMARY_COLLECTION_NAME,
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = build_parser().parse_args()
    if not args.organization_id or not args.user_id:
        raise SystemExit(
            "Provide --organization-id and --user-id, or configure "
            "SAVIRACORTEX_EVAL_ORGANIZATION_ID and SAVIRACORTEX_EVAL_USER_ID."
        )
    if not args.collection or not args.summary_collection:
        raise SystemExit(
            "Configure dedicated evaluation chunk and summary Qdrant collections."
        )
    if (
        (args.limit is not None and args.limit < 1)
    ):
        raise SystemExit("Invalid workflow threshold or --limit value.")

    try:
        organization_id = UUID(args.organization_id)
        user_id = UUID(args.user_id)
    except ValueError as exc:
        raise SystemExit(
            "Evaluation organization/user IDs must be valid UUIDs. "
            "Check SAVIRACORTEX_EVAL_USER_ID in .env."
        ) from exc

    report = asyncio.run(
        evaluate_dataset(
            organization_id=organization_id,
            user_id=user_id,
            chunk_collection_name=args.collection,
            summary_collection_name=args.summary_collection,
            dataset_path=args.dataset.expanduser().resolve(),
            max_retrieval_attempts=args.max_retrieval_attempts,
            compression_document_threshold=args.compression_document_threshold,
            limit=args.limit,
        )
    )
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else DEFAULT_RESULTS_DIRECTORY
        / f"deepeval_production_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(f"Goldens evaluated: {report['golden_count']}")
    print(f"Qdrant chunk collection: {report['qdrant_chunk_collection']}")
    print(f"Qdrant summary collection: {report['qdrant_summary_collection']}")
    print(f"Orchestrator: {report['orchestrator']}")
    print("Metric mean scores:")
    for name, values in report["summary"].items():
        score = values["mean_score"]
        print(f"  {name}: {score if score is not None else 'N/A'}")
    print(f"Detailed report: {output_path}")


if __name__ == "__main__":
    main()
