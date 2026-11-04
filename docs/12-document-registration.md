# 12. Document Registration and Version Creation

Registration is implemented by `app/services/document_registration/registration_service.py`. It provides separate operations for creating a new logical document and adding a new version to an existing logical document.

## New document

`register_new_document()` validates the document and version data, then creates a `Document` and its first `DocumentVersion` (version number 1) inside a SQLAlchemy nested transaction/savepoint. The new version is assigned `pending` status. Required data includes a non-empty title and document type, original filename, storage key, non-empty summary, and a 64-character hexadecimal file SHA-256 hash. Optional metadata includes description, content hash, version label, effective dates and page count.

## New version

`register_new_version()` creates a pending version for an existing document in the specified organization. It locks the parent document row while calculating the next version number, rejects missing or archived documents, finds the current active version, and records that version in `supersedes_version_id`. The caller supplies the new version's storage key and metadata. The method does not itself upload a file or activate the new version.

## Pending state and transaction ownership

Registration does not mean the document is searchable as active. A newly registered version remains pending until indexing completes and the indexing orchestrator commits activation.

The registration service does not commit the outer SQLAlchemy transaction. It uses a nested transaction/savepoint and leaves the outer commit/rollback to its caller. The ingestion workflow currently calls `register_new_document()` for a new logical document; it does not automatically route a potential match into `register_new_version()`. The ingestion service uploads the original PDF, registers a new logical document/version, and commits; if upload or registration fails, it rolls back and attempts object cleanup. Do not introduce an early commit without reviewing the cross-store consistency implications.

## Related modules

- `app/models/documents.py`
- `app/models/document_versions.py`
- `app/repositories/document_repositories.py`
- `app/repositories/document_version_repositories.py`
- `tests/services/test_document_registration.py`
