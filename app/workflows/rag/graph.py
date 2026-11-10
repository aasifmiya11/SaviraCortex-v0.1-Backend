"""LangGraph construction for the persisted single-pass RAG workflow."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.Generation import GenerationAgent
from app.services.retrieval.retrieval_service import RetrievalOrchestrator
from app.validation import StaticValidationLayer
from langgraph.graph import END, START, StateGraph

from app.memory.cross_thread_memory import retrieve_cross_thread_memories
from app.workflows.rag.nodes.generation import create_generation_node
from app.workflows.rag.nodes.input_validation import input_validation_node
from app.workflows.rag.nodes.policy_response import policy_response_node
from app.workflows.rag.nodes.retriever import create_retriever_node
from app.workflows.rag.nodes.runtime_input_guardrails import runtime_input_guardrails_node
from app.workflows.rag.nodes.static_validation import create_static_validation_node
from app.workflows.rag.routing import route_after_runtime_guardrails
from app.workflows.rag.state import RAGWorkflowState


def create_rag_graph(
    *,
    retriever: RetrievalOrchestrator,
    generation_agent: GenerationAgent,
    validator: StaticValidationLayer,
    checkpointer: Any | None = None,
    store: Any | None = None,
    generation_event_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
):
    """Build input validation -> guardrails -> retrieval -> generation -> output validation."""
    graph = StateGraph(RAGWorkflowState)
    graph.add_node("input_validation", input_validation_node)
    graph.add_node("runtime_input_guardrails", runtime_input_guardrails_node)
    graph.add_node("policy_response", policy_response_node)
    graph.add_node("retriever", create_retriever_node(retriever))
    graph.add_node(
        "generation",
        create_generation_node(generation_agent, event_callback=generation_event_callback),
    )
    graph.add_node("static_validation", create_static_validation_node(validator))

    graph.add_edge(START, "input_validation")
    graph.add_edge("input_validation", "runtime_input_guardrails")
    next_nodes = {
        "valid": "memory_retriever" if store is not None else "retriever",
        "off_topic": "policy_response",
        "blocked": "policy_response",
        "invalid": END,
    }
    graph.add_conditional_edges(
        "runtime_input_guardrails",
        route_after_runtime_guardrails,
        next_nodes,
    )
    if store is not None:
        graph.add_node("memory_retriever", retrieve_cross_thread_memories)
        graph.add_edge("memory_retriever", "retriever")
    graph.add_edge("retriever", "generation")
    graph.add_edge("generation", "static_validation")
    graph.add_edge("policy_response", "static_validation")
    graph.add_edge("static_validation", END)
    return graph.compile(checkpointer=checkpointer, store=store)
