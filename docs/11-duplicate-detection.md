# 11. Duplicate Detection and Matching

Duplicate matching is implemented under `app/services/document_matching/` and invoked by document ingestion.

## Matching components

- `hash_matcher.py`: exact file/content hash matching.
- `summary_matcher.py`: compares document summaries/metadata for possible semantic or near-duplicate matches.
- `matching_orchestrator.py`: coordinates matching stages and returns a unified outcome.

## Matching outcomes

The ingestion contract distinguishes exact duplicates from possible matches. Exact file or normalized-content matches return a duplicate outcome and avoid a second upload/registration. Potential matches return a review-required outcome rather than silently merging records. No match permits a new object upload and pending registration.

## Hashes and scope

The ingestion flow calculates both a file hash and normalized-content hash. File hash identifies byte-identical inputs; content hash supports recognizing content-equivalent PDFs despite differences in file packaging/metadata. Matching is organization-scoped. Tests cover stable lock-key generation and matching orchestration behavior.

## Review policy

A potential match is not proof of duplication. Human review should compare document identity, content, organization ownership and version context before deciding whether the incoming file represents a new document or a new version. Do not automatically discard a potential match.

## Source references

See `app/rag/ingestion/hash_service.py`, `app/services/document_matching/`, and `tests/services/test_document_hash_matcher.py`, `test_document_summary_matcher.py`, and `test_document_matching_orchestrator.py`.
