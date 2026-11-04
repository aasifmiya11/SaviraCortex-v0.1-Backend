# 12. Document Registration

Registration is implemented by `app/services/document_registration/registration_service.py` and is called after ingestion has uploaded a file and concluded that no duplicate/review decision blocks registration.

## Responsibilities

The registration service creates or associates a logical document and creates a pending document-version record in PostgreSQL. The version record retains file-level metadata such as original filename, object storage key, file/content hashes, page count and generated summary/description fields. Exact field names and validation constraints are defined in the SQLAlchemy models and service.

## Pending state

Registration does not mean the document is already searchable. A newly registered version is pending until indexing completes and lifecycle activation is committed by the indexing workflow.

## Transaction ownership

The service participates in the caller's database session/transaction. Ingestion handles rollback and storage cleanup when registration fails after an object upload. Review service/repository code before introducing a commit boundary; an early commit can make cleanup and consistency harder.

## Related modules

- `app/models/documents.py`
- `app/models/document_versions.py`
- `app/repositories/document_repositories.py`
- `app/repositories/document_version_repositories.py`
- `tests/services/test_document_registration.py`
