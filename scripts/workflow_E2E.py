"""Run three real end-to-end SaviraCortex RAG workflow examples.

Run from the project root:

    uv run python scripts/workflow_E2E.py \
        --organization-id <ORGANIZATION_UUID> \
        --user-id <USER_UUID>

The script uses the configured PostgreSQL, Qdrant, embedding, reranker, and
LLM services. It does not ingest, edit, or delete documents. Existing Qdrant
store initialization may ensure configured collections and indexes exist.
The database session remains open for the full workflow run because
authorization retrieval uses the request-scoped SQLAlchemy session.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.Context_compression import ContextCompressionAgent
from app.agents.Evidence_evaluator import EvidenceEvaluatorAgent
from app.agents.Generation import GenerationAgent
from app.agents.Multi_query_generator.agent import MultiQueryGeneratorAgent
from app.agents.Retrieval_expansion import RetrievalExpansionAgent
from app.core.database import get_db_session
from app.rag.retrieval.adaptive_k_selector import AdaptiveKSelector
from app.rag.retrieval.candidate_document_generator import (
    CandidateDocumentGenerator,
)
from app.rag.retrieval.cross_encoder_reranker import CrossEncoderReranker
from app.rag.retrieval.global_fusion import global_result_fusion
from app.rag.retrieval.pipeline import retrieval_pipeline
from app.rag.vector_stores.qdrant_summary import summary_store
from app.repositories.authorization_repository import AuthorizationRepository
from app.services.authorization.authorization_service import AuthorizationService
from app.services.retrieval.retrieval_service import RetrievalOrchestrator
from app.validation import StaticValidationLayer
from app.workflows.rag.config import RAGWorkflowConfig
from app.workflows.rag.graph import create_rag_graph


SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "1. SIMPLE QUERY (NO CONVERSATION HISTORY)",
        "query": "What is the company's annual leave entitlement?",
        "context": [],
        "description": "A direct question with no previous conversation.",
    },
    {
        "name": "2. FOLLOW-UP QUERY (WITH CONVERSATION HISTORY)",
        "query": "How many days can I carry forward?",
        "context": [
            HumanMessage(
                content="I am reviewing the company's annual leave policy."
            ),
            AIMessage(
                content=(
                    "I can help with that. What would you like to know "
                    "about the leave policy?"
                )
            ),
        ],
        "description": (
            "A short follow-up whose meaning depends on the previous messages."
        ),
    },
    {
        "name": "3. MESSY QUERY (WHITESPACE NORMALIZATION)",
        "query": (
            "   What   is the company's     sick leave policy?\n"
            "       Are there any eligibility conditions?   "
        ),
        "context": [],
        "description": (
            "A query with repeated spaces and line breaks; input validation "
            "should normalize whitespace without rewriting its meaning."
        ),
    },
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run real user-query-to-validated-answer RAG workflow examples."
    )
    parser.add_argument(
        "--organization-id",
        required=True,
        type=UUID,
        help="Organization UUID used for document authorization.",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        type=UUID,
        help="User UUID used for document authorization.",
    )
    parser.add_argument(
        "--max-retrieval-attempts",
        type=int,
        default=3,
        help="Maximum total retrieval attempts per query (default: 3).",
    )
    return parser


def print_section(title: str) -> None:
    print("\n" + "=" * 96)
    print(title)
    print("=" * 96)


def build_workflow(db_session, *, max_retrieval_attempts: int):
    """Compose the real workflow from existing application components."""
    authorization_service = AuthorizationService(
        AuthorizationRepository(db_session)
    )
    retriever = RetrievalOrchestrator(
        authorization_service=authorization_service,
        multi_query_agent=MultiQueryGeneratorAgent(),
        candidate_document_generator=CandidateDocumentGenerator(
            summary_store=summary_store,
        ),
        hybrid_retrieval_pipeline=retrieval_pipeline,
        global_fusion=global_result_fusion,
        cross_encoder_reranker=CrossEncoderReranker(),
        adaptive_k_selector=AdaptiveKSelector(),
    )

    return create_rag_graph(
        retriever=retriever,
        evaluator=EvidenceEvaluatorAgent(),
        retrieval_expansion_agent=RetrievalExpansionAgent(),
        context_compression_agent=ContextCompressionAgent(),
        generation_agent=GenerationAgent(),
        validator=StaticValidationLayer(),
        config=RAGWorkflowConfig(
            max_retrieval_attempts=max_retrieval_attempts,
            compression_document_threshold=15,
        ),
    )


def model_data(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    raise TypeError(f"Expected a Pydantic model or dictionary, got {type(value).__name__}.")


async def run_scenario(
    *,
    graph,
    scenario: dict[str, Any],
    organization_id: UUID,
    user_id: UUID,
) -> bool:
    print_section(scenario["name"])
    print(scenario["description"])
    print(f"Original query: {scenario['query']!r}")
    print(f"Conversation messages: {len(scenario['context'])}")

    result = await graph.ainvoke(
        {
            "query": scenario["query"],
            "organization_id": organization_id,
            "user_id": user_id,
            "context": scenario["context"],
        }
    )

    print("\n--- INPUT VALIDATION ---")
    print(f"Valid: {result.get('is_valid')}")
    print(f"Normalized query: {result.get('query')!r}")
    if result.get("validation_error"):
        print(f"Validation error: {result['validation_error']}")
        return False

    print("\n--- RETRIEVAL ---")
    print(f"Retrieval attempts: {result.get('retrieval_attempt', 0)}")
    print(f"Accumulated documents: {len(result.get('retrieved_documents') or [])}")
    print(f"Context compressed: {result.get('context_compressed', False)}")

    diagnostics = result.get("retrieval_diagnostics") or {}
    for attempt in diagnostics.get("attempts", []):
        print(
            f"Attempt {attempt.get('attempt')}: "
            f"selected={attempt.get('selected_count')}, "
            f"reranked={attempt.get('reranked_count')}, "
            f"branches={attempt.get('branch_count')}, "
            f"reason={attempt.get('retrieval_reason')}"
        )

    print("\n--- EVIDENCE EVALUATION ---")
    print(f"Evidence sufficient: {result.get('is_sufficient')}")
    for item in result.get("missing_information") or []:
        print(f"Missing information: {item}")

    print("\n--- GENERATION ---")
    generation = result.get("generation_output")
    if generation is None:
        print("Generation did not produce an output.")
        return False

    generation_data = model_data(generation)
    print(f"Status: {generation_data.get('status')}")
    for segment in generation_data.get("segments", []):
        print(f"\n{segment.get('text', '')}")
        citations = segment.get("citations") or []
        if citations:
            print("Citations: " + ", ".join(citations))

    print("\n--- STATIC VALIDATION ---")
    validation = result.get("validation_result")
    if validation is None:
        print("Static validation did not produce a result.")
        return False

    validation_data = model_data(validation)
    print(f"Valid: {validation_data.get('is_valid')}")
    for error in validation_data.get("errors", []):
        print(f"ERROR: {error}")
    for warning in validation_data.get("warnings", []):
        print(f"WARNING: {warning}")

    citations = validation_data.get("citations") or []
    if citations:
        print("Resolved citation metadata:")
        for citation in citations:
            print(f"  {citation}")

    return bool(validation_data.get("is_valid"))


async def main() -> int:
    args = build_parser().parse_args()
    if args.max_retrieval_attempts < 1:
        raise SystemExit("--max-retrieval-attempts must be at least 1.")

    print_section("SAVIRACORTEX — END-TO-END RAG WORKFLOW")
    print(f"Organization: {args.organization_id}")
    print(f"User: {args.user_id}")
    print(f"Scenarios: {len(SCENARIOS)}")
    print(
        "This run uses live configured services and may call the LLM, "
        "embedding endpoint, reranker, PostgreSQL, and Qdrant."
    )
    print("No application records are created or modified.")

    passed = 0
    failed = 0

    # Keep the request-scoped DB session alive while the graph runs. The
    # RetrievalOrchestrator calls the synchronous authorization repository.
    with get_db_session() as db_session:
        graph = build_workflow(
            db_session,
            max_retrieval_attempts=args.max_retrieval_attempts,
        )

        for scenario in SCENARIOS:
            try:
                success = await run_scenario(
                    graph=graph,
                    scenario=scenario,
                    organization_id=args.organization_id,
                    user_id=args.user_id,
                )
            except Exception as exc:
                failed += 1
                print(
                    f"\nSCENARIO ERROR: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue

            if success:
                passed += 1
            else:
                failed += 1

    print_section("END-TO-END RUN SUMMARY")
    print(f"Passed: {passed}/{len(SCENARIOS)}")
    print(f"Failed: {failed}/{len(SCENARIOS)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
