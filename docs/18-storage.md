# 18. Storage Architecture

## PostgreSQL

The relational database is the source of truth for organization/user relationships, document identity, version metadata, ACLs and lifecycle status. It is accessed through SQLAlchemy. Schema creation/reset behavior is described in [Database Design](06-database-design.md); note that the current reset script is destructive.

## Backblaze B2

`app/storage/b2_client.py` and `file_storage.py` implement object storage access using boto3 and an S3-compatible B2 endpoint. The original uploaded PDF is retained in the configured bucket and key namespace. The application key, endpoint, region, bucket and prefix are validated when storage helpers initialize. The B2 client is cached with `lru_cache`.

Application object keys follow this structure:

```text
<prefix>/organizations/<organization_id>/documents/<document_id>/versions/<version_id>.pdf
```

Uploads are followed by a HEAD request and a size comparison. Downloads can target a local path or binary file object. The storage abstraction also supports existence checks, metadata lookup, deletion and temporary presigned download URLs (15-minute default).

Object keys should be treated as opaque identifiers. Do not expose bucket credentials or construct public URLs unless the deployment's access policy explicitly allows it.

## Qdrant chunk collection

`app/rag/vector_stores/qdrant.py` manages the chunk vector collection. Payload indexes are managed by `qdrant_payload_indexes.py`. Chunk payloads contain page content and LangChain metadata used for organization, document, version, page, chunk and lifecycle filtering. The configured local Hugging Face embedding model is `sentence-transformers/all-MiniLM-L6-v2` by default, with CUDA selected when available and CPU otherwise.

## Qdrant summary collection

`qdrant_summary.py` manages document-version summary vectors in a separate collection. Each summary point is keyed by the document-version ID and stores organization/document/version identifiers, version number, title, summary and lifecycle status. Its configured name is `QDRANT_SUMMARY_COLLECTION_NAME`, defaulting to the chunk collection name plus `_summaries` when available.

## Redis-compatible cache

The async client in `app/core/redis.py` is created lazily and reused for the active event loop. It checks for a configured URI, uses response decoding, connection/socket timeouts and periodic health checks. It is closed with `close_redis()`. The authorization cache service is a separate helper; the current retrieval orchestrator does not call it.

## Separate root-level storage utility

The repository also contains `storage.py`, a standalone Backblaze S3-compatible command-line utility with test, upload, list, download, read and delete commands. It is separate from the application abstraction in `app/storage/` and has its own command-line argument handling.

## Cross-store consistency

There is no distributed transaction across PostgreSQL, B2 and Qdrant. Ingestion compensates for upload/registration failures. Indexing compensates for pre-commit vector writes, preserves external data when commit outcome is uncertain, and reports post-commit synchronization failures for reconciliation. Backups should cover relational data, original objects and both Qdrant collections, with a documented restore order and consistency check.
