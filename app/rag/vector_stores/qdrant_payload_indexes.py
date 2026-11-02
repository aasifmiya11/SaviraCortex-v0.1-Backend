from __future__ import annotations

from qdrant_client import models


REQUIRED_PAYLOAD_INDEXES = {
    "metadata.organization_id": models.PayloadSchemaType.KEYWORD,
    "metadata.document_version_id": models.PayloadSchemaType.KEYWORD,
    "metadata.document_id": models.PayloadSchemaType.KEYWORD,
    "metadata.status": models.PayloadSchemaType.KEYWORD,
}


def ensure_payload_indexes(qdrant_client, collection_name: str) -> None:
    """
    Ensure the required Qdrant payload indexes exist.

    Existing compatible indexes are preserved. Missing indexes are created.
    Incompatible existing indexes raise RuntimeError. All existing indexes
    are validated before any missing index is created.
    """
    collection_info = qdrant_client.get_collection(
        collection_name=collection_name
    )
    existing_schema = collection_info.payload_schema or {}
    missing_indexes = []

    for field_name, expected_type in REQUIRED_PAYLOAD_INDEXES.items():
        existing_index = existing_schema.get(field_name)
        if existing_index is None:
            missing_indexes.append((field_name, expected_type))
            continue

        existing_type = getattr(
            existing_index,
            "data_type",
            existing_index,
        )
        if existing_type != expected_type:
            raise RuntimeError(
                f"Incompatible Qdrant payload index for "
                f"'{field_name}'. Expected {expected_type}, "
                f"found {existing_type}."
            )

    for field_name, expected_type in missing_indexes:
        qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=expected_type,
            wait=True,
        )
