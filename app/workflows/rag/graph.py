"""LangGraph construction for the single-pass RAG workflow."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.Generation import GenerationAgent
from app.services.retrieval.retrieval_service import RetrievalOrchestrator
from app.validation import StaticValidationLayer
from langgraph.graph import END, START, StateGraph

from app.workflows.rag.nodes.generation import create_generation_node
from app.workflows.rag.nodes.input_validation import input_validation_node
from app.workflows.rag.nodes.retriever import create_retriever_node
from app.workflows.rag.nodes.static_validation import create_static_validation_node
from app.workflows.rag.routing import route_after_validation
from app.workflows.rag.state import RAGWorkflowState


def create_rag_graph(
    *,
    retriever: RetrievalOrchestrator,
    generation_agent: GenerationAgent,
    validator: StaticValidationLayer,
    generation_event_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
):
    """Build a one-pass graph: validate -> retrieve/select -> generate -> validate citations.

    Evidence sufficiency evaluation, query revision/retrieval expansion, and
    context compression are intentionally not part of this execution path.
    """
    graph = StateGraph(RAGWorkflowState)
    graph.add_node("input_validation", input_validation_node)
    graph.add_node("retriever", create_retriever_node(retriever))
    graph.add_node(
        "generation",
        create_generation_node(generation_agent, event_callback=generation_event_callback),
    )
    graph.add_node("static_validation", create_static_validation_node(validator))

    graph.add_edge(START, "input_validation")
    graph.add_conditional_edges(
        "input_validation",
        route_after_validation,
        {"valid": "retriever", "invalid": END},
    )
    graph.add_edge("retriever", "generation")
    graph.add_edge("generation", "static_validation")
    graph.add_edge("static_validation", END)
    return graph.compile()
