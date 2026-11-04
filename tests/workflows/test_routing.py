from app.workflows.rag.config import RAGWorkflowConfig
from app.workflows.rag.routing import (
    route_after_evaluation,
    route_after_validation,
)


def test_invalid_query_routes_to_end():
    assert route_after_validation({"is_valid": False}) == "invalid"


def test_valid_query_routes_to_retriever():
    assert route_after_validation({"is_valid": True}) == "valid"


def test_insufficient_evidence_routes_to_expansion_before_attempt_limit():
    state = {
        "is_sufficient": False,
        "retrieval_attempt": 1,
        "retrieved_documents": [{"chunk_id": "a:0"}],
    }
    assert route_after_evaluation(state) == "expand"


def test_third_insufficient_attempt_skips_expansion_and_compression_for_15_docs():
    state = {
        "is_sufficient": False,
        "retrieval_attempt": 3,
        "retrieved_documents": [{} for _ in range(15)],
    }
    assert route_after_evaluation(state) == "generate"


def test_more_than_15_accumulated_documents_routes_to_compression():
    state = {
        "is_sufficient": True,
        "retrieval_attempt": 1,
        "retrieved_documents": [{} for _ in range(16)],
    }
    assert route_after_evaluation(state) == "compress"


def test_attempt_limit_is_configurable_and_checked_before_expansion():
    config = RAGWorkflowConfig(max_retrieval_attempts=2)
    state = {
        "is_sufficient": False,
        "retrieval_attempt": 2,
        "retrieved_documents": [{} for _ in range(15)],
    }
    assert route_after_evaluation(state, config) == "generate"


def test_workflow_config_rejects_invalid_values():
    import pytest

    with pytest.raises(ValueError):
        RAGWorkflowConfig(max_retrieval_attempts=0)
    with pytest.raises(ValueError):
        RAGWorkflowConfig(compression_document_threshold=-1)
