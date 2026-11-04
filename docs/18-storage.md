# 18. Storage Architecture

## PostgreSQL

The relational database is the source of truth for organization/user relationships, document identity, version metadata, ACLs and lifecycle status. It is accessed through SQLAlchemy.

## Backblaze B2

`app/storage/b2_client.py` and `file_storage.py` implement object storage access using boto3 and an S3-compatible B2 endpoint. The original uploaded PDF is retained in the configured bucket and key namespace. Configuration includes key ID, application key, bucket, region, endpoint and prefix.

Object keys should be treated as opaque identifiers. Do not expose bucket credentials or construct public URLs unless the deployment's access policy explicitly allows it.

## Qdrant chunk collection

`app/rag/vector_stores/qdrant.py` manages the chunk vector collection. Payload indexes are managed by `qdrant_payload_indexes.py`. Payload metadata supports filtering by document, version, organization and lifecycle attributes.

## Qdrant summary collection

`qdrant_summary.py` manages document-level summary vectors in a separate collection. Its configured name is `QDRANT_SUMMARY_COLLECTION_NAME`, defaulting to the chunk collection name plus `_summaries` when available.

## Redis-compatible cache

The async client in `app/core/redis.py` is created lazily and reused for the active event loop. It checks for a configured URI, uses response decoding, connection/socket timeouts and periodic health checks. It is closed with `close_redis()`.

## Cross-store consistency

There is no distributed transaction across PostgreSQL, B2 and Qdrant. Services must use compensating cleanup and reconciliation. Backups should cover relational data, original objects and vector indexes, with a documented restore order and consistency check.
