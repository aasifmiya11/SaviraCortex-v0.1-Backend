# 23. Execution Guide

## Current entry points

The root `main.py` defines a `main()` that prints a greeting. `app/main.py` currently prints `hi`. Neither is an application server startup path. No API routes were found in `app/api/v1/`.

## Calling service workflows

The functional entry points are service classes and scripts:

- Ingestion: `DocumentIngestionService.ingest_pdf(file_path, organization_id=...)`.
- Registration: `DocumentRegistrationService.register_new_document(...)` and `register_new_version(...)`.
- Indexing: `DocumentIndexingOrchestrator.index_pending_version(version_id, organization_id=...)`.
- Retrieval: async `RetrievalOrchestrator.retrieve(...)`.
- Authorization: `AuthorizationService.get_authorized_document_ids(...)` and `get_authorized_document_catalog(...)`.

Exact constructor arguments and method signatures are defined in source and tests. Services use dependency injection for database sessions, external clients and model collaborators.

## Demo ingestion command

`scripts/ingestion.py` accepts a PDF path and optional `--skip-index`. By default it creates a fresh demo organization, user and owner membership, ingests the PDF, associates the uploader, and indexes the version if ingestion returns `registered_pending`. It prints generated IDs and stage results. It does not expose an HTTP endpoint.

```powershell
uv run python scripts/ingestion.py "C:\path\to\document.pdf"
uv run python scripts/ingestion.py "C:\path\to\document.pdf" --skip-index
```

Because each run creates a new demo tenant/user, treat it as a development demonstration, not a reusable production ingestion interface.

## Recommended caller sequence

A higher-level application should authenticate the user, resolve organization membership, call the appropriate service with trusted identifiers, handle structured outcomes/errors, and close database/Redis clients at lifecycle boundaries. This is integration guidance, not an implemented HTTP endpoint.

## Operational scripts

See [Scripts and CLI](20-scripts-and-cli.md). In particular, database reset and Qdrant wipe commands are destructive; inspect their behavior and target environment before running.
