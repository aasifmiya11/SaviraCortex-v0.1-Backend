# 23. Execution Guide

## Current entry points

The root `main.py` defines a `main()` that prints a greeting. `app/main.py` currently prints `hi`. Neither is an application server startup path. No API routes were found in `app/api/v1/`.

## Calling service workflows

The functional entry points are service classes and scripts:
- Ingestion: `DocumentIngestionService.ingest_pdf(...)`.
- Registration: `DocumentRegistrationService` methods in the registration service.
- Indexing: indexing service/orchestrator methods under `app/services/document_indexing/`.
- Retrieval: methods on the retrieval service under `app/services/retrieval/`.
- Authorization: authorization service methods under `app/services/authorization/`.

Exact constructor arguments and method signatures are defined in source and tests. Use dependency injection for database sessions, external clients and model collaborators as the tests do.

## Recommended caller sequence

A higher-level application should authenticate the user, resolve organization membership, call the appropriate service with trusted identifiers, handle structured outcomes/errors, and close database/Redis clients at lifecycle boundaries. This is integration guidance, not an implemented HTTP endpoint.

## Operational scripts

See [Scripts and CLI](20-scripts-and-cli.md). Inspect a script before running it; scripts may create tables, mutate indexes or access external stores.
