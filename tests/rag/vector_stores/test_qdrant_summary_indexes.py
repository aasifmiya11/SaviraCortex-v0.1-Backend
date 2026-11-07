from types import SimpleNamespace
from unittest.mock import MagicMock

from qdrant_client import models

from app.rag.vector_stores.qdrant_summary import QdrantSummaryStore


def test_summary_collection_creates_document_id_keyword_index():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(payload_schema={})

    QdrantSummaryStore(client=client, collection_name="test_summaries")

    client.create_payload_index.assert_any_call(
        collection_name="test_summaries",
        field_name="document_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
        wait=True,
    )


def test_summary_collection_preserves_existing_document_id_index():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        payload_schema={
            "document_id": SimpleNamespace(
                data_type=models.PayloadSchemaType.KEYWORD
            ),
            "organization_id": SimpleNamespace(
                data_type=models.PayloadSchemaType.KEYWORD
            ),
            "document_version_id": SimpleNamespace(
                data_type=models.PayloadSchemaType.KEYWORD
            ),
        }
    )

    QdrantSummaryStore(client=client, collection_name="test_summaries")

    client.create_payload_index.assert_not_called()
