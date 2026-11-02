
import pytest

from langchain_core.documents import Document

from app.rag.retrieval import pipeline as pipeline_module
from app.rag.retrieval.fusion import reciprocal_rank_fusion
from app.rag.retrieval.pipeline import HybridRetrievalPipeline


def make_document(
    content,
    *,
    document_id="doc-1",
    version_id="version-1",
    chunk_index=0,
    status="active",
):
    return Document(
        page_content=content,
        metadata={
            "document_id": document_id,
            "document_version_id": version_id,
            "chunk_index": chunk_index,
            "status": status,
            "source_filename": "sample.pdf",
            "page": 1,
        },
    )


class FakeRetriever:
    def __init__(self, results=None):
        self.results = results or []
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.results


def test_hybrid_pipeline_forwards_status_to_both_retrievers(monkeypatch):
    bm25 = FakeRetriever()
    dense = FakeRetriever()

    monkeypatch.setattr(pipeline_module, "bm25_retriever", bm25)
    monkeypatch.setattr(pipeline_module, "dense_retriever", dense)

    pipeline = HybridRetrievalPipeline()

    pipeline.search(
        query="machine learning",
        organization_id="org-1",
        status="pending",
    )

    assert bm25.calls[0]["status"] == "pending"
    assert dense.calls[0]["status"] == "pending"
    assert bm25.calls[0]["organization_id"] == "org-1"
    assert dense.calls[0]["organization_id"] == "org-1"


@pytest.mark.parametrize(
    ("mode", "expected_bm25_calls", "expected_dense_calls"),
    [
        ("hybrid", 1, 1),
        ("bm25", 1, 0),
        ("dense", 0, 1),
    ],
)
def test_pipeline_calls_only_requested_retrievers(
    monkeypatch,
    mode,
    expected_bm25_calls,
    expected_dense_calls,
):
    bm25 = FakeRetriever()
    dense = FakeRetriever()

    monkeypatch.setattr(pipeline_module, "bm25_retriever", bm25)
    monkeypatch.setattr(pipeline_module, "dense_retriever", dense)

    pipeline = HybridRetrievalPipeline()
    pipeline.search(
        "machine learning",
        organization_id="org-1",
        mode=mode,
    )

    assert len(bm25.calls) == expected_bm25_calls
    assert len(dense.calls) == expected_dense_calls


def test_pipeline_uses_active_status_by_default(monkeypatch):
    bm25 = FakeRetriever()
    dense = FakeRetriever()

    monkeypatch.setattr(pipeline_module, "bm25_retriever", bm25)
    monkeypatch.setattr(pipeline_module, "dense_retriever", dense)

    HybridRetrievalPipeline().search(
        "machine learning",
        organization_id="org-1",
    )

    assert bm25.calls[0]["status"] == "active"
    assert dense.calls[0]["status"] == "active"
    assert bm25.calls[0]["organization_id"] == "org-1"
    assert dense.calls[0]["organization_id"] == "org-1"


def test_pipeline_preserves_result_structure(monkeypatch):
    document = make_document("Machine learning content")

    bm25 = FakeRetriever([(document, 0.8)])
    dense = FakeRetriever([(document, 0.9)])

    monkeypatch.setattr(pipeline_module, "bm25_retriever", bm25)
    monkeypatch.setattr(pipeline_module, "dense_retriever", dense)

    result = HybridRetrievalPipeline().search(
        "machine learning",
        organization_id="org-1",
    )

    assert result["query"] == "machine learning"
    assert result["mode"] == "hybrid"
    assert result["result_count"] == 1
    assert result["results"][0]["page_content"] == "Machine learning content"
    assert result["results"][0]["metadata"]["status"] == "active"
    assert "Machine learning content" in result["context"]


def test_pipeline_rejects_empty_status():
    pipeline = HybridRetrievalPipeline()

    with pytest.raises(ValueError, match="status cannot be empty"):
        pipeline.search(
            "machine learning",
            organization_id="org-1",
            status=" ",
        )


def test_hybrid_retrieval_requires_organization_id():
    pipeline = HybridRetrievalPipeline()

    with pytest.raises(ValueError, match="organization_id cannot be empty"):
        pipeline.search("machine learning", organization_id=" ")


def test_rrf_merges_same_version_chunk_from_both_retrievers():
    document = make_document("Shared chunk")

    result = reciprocal_rank_fusion(
        [
            [(document, 0.9)],
            [(document, 0.8)],
        ],
        k=60,
    )

    assert len(result) == 1
    assert result[0][0].page_content == "Shared chunk"
    assert result[0][1] == pytest.approx(2 / 61)


def test_rrf_keeps_different_versions_separate():
    version_one = make_document(
        "Old version content",
        version_id="version-1",
    )
    version_two = make_document(
        "New version content",
        version_id="version-2",
    )

    result = reciprocal_rank_fusion(
        [
            [(version_one, 0.9)],
            [(version_two, 0.8)],
        ]
    )

    assert len(result) == 2

    returned_versions = {
        document.metadata["document_version_id"]
        for document, _ in result
    }

    assert returned_versions == {"version-1", "version-2"}


def test_rrf_validates_weight_count():
    with pytest.raises(ValueError, match="weights must match"):
        reciprocal_rank_fusion(
            [[], []],
            weights=[1.0],
        )


def test_rrf_validates_k():
    with pytest.raises(ValueError, match="RRF constant k"):
        reciprocal_rank_fusion([], k=0)
