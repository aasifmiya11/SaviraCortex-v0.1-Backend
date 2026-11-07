"""LangGraph construction and compilation for the RAG workflow."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.Context_compression import ContextCompressionAgent
from app.agents.Evidence_evaluator import EvidenceEvaluatorAgent
from app.agents.Generation import GenerationAgent
from app.agents.Retrieval_expansion import RetrievalExpansionAgent
from app.services.retrieval.retrieval_service import RetrievalOrchestrator
from app.validation import StaticValidationLayer
from langgraph.graph import END, START, StateGraph

from app.workflows.rag.config import RAGWorkflowConfig
from app.workflows.rag.nodes.context_compression import create_context_compression_node
from app.workflows.rag.nodes.evidence_evaluator import create_evidence_evaluator_node
from app.workflows.rag.nodes.generation import create_generation_node
from app.workflows.rag.nodes.input_validation import input_validation_node
from app.workflows.rag.nodes.retrieval_expansion import create_retrieval_expansion_node
from app.workflows.rag.nodes.retriever import create_retriever_node
from app.workflows.rag.nodes.static_validation import create_static_validation_node
from app.workflows.rag.routing import route_after_evaluation, route_after_validation
from app.workflows.rag.state import RAGWorkflowState


async def _noop_generation_event(_event: dict[str, Any]) -> None:
    return None


def create_rag_graph(
    *,
    retriever: RetrievalOrchestrator,
    evaluator: EvidenceEvaluatorAgent,
    retrieval_expansion_agent: RetrievalExpansionAgent,
    context_compression_agent: ContextCompressionAgent,
    generation_agent: GenerationAgent,
    validator: StaticValidationLayer,
    config: RAGWorkflowConfig | None = None,
    generation_event_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
):
    """Create and compile the RAG graph from application-managed dependencies.

    Model clients and retrieval dependencies are injected by the application
    composition layer; importing this module does not initialize services.
    """
    workflow_config = config or RAGWorkflowConfig()
    graph = StateGraph(RAGWorkflowState)
    graph.add_node("input_validation", input_validation_node)
    graph.add_node("retriever", create_retriever_node(retriever))
    graph.add_node("evidence_evaluator", create_evidence_evaluator_node(evaluator))
    graph.add_node("retrieval_expansion", create_retrieval_expansion_node(retrieval_expansion_agent))
    graph.add_node("context_compression", create_context_compression_node(context_compression_agent))
    graph.add_node(
        "generation",
        create_generation_node(generation_agent, event_callback=generation_event_callback),
    )
    graph.add_node("static_validation", create_static_validation_node(validator))

    graph.add_edge(START, "input_validation")
    graph.add_conditional_edges(
        "input_validation", route_after_validation,
        {"valid": "retriever", "invalid": END},
    )
    graph.add_edge("retriever", "evidence_evaluator")
    graph.add_conditional_edges(
        "evidence_evaluator",
        lambda state: route_after_evaluation(state, workflow_config),
        {"expand": "retrieval_expansion", "compress": "context_compression", "generate": "generation"},
    )
    graph.add_edge("retrieval_expansion", "retriever")
    graph.add_edge("context_compression", "generation")
    graph.add_edge("generation", "static_validation")
    graph.add_edge("static_validation", END)
    return graph.compile()
