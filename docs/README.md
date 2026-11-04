# Voice-AI Technical Documentation

**Documentation status:** initial code-based documentation  
**Repository:** `E:\Voice-AI`  
**Review baseline:** 4 November 2026

This documentation describes the implementation present in the repository at the time of review. It is not a product specification and does not imply that planned or placeholder components are implemented.

## Reading order

1. [Project overview](01-project-overview.md)
2. [System architecture](02-system-architecture.md)
3. [Technology stack](03-technology-stack.md)
4. [Project structure](04-project-structure.md)
5. [Configuration](05-configuration.md)
6. [Database design](06-database-design.md)
7. [Authorization](07-authorization.md)
8. [PDF processing](08-pdf-processing.md)
9. [Document ingestion](09-document-ingestion.md)
10. [AI agents](10-ai-agents.md)
11. [Duplicate detection](11-duplicate-detection.md)
12. [Document registration](12-document-registration.md)
13. [Document indexing](13-document-indexing.md)
14. [Version lifecycle](14-version-lifecycle.md)
15. [Retrieval architecture](15-retrieval-architecture.md)
16. [Candidate generation](16-candidate-generation.md)
17. [Retrieval optimization](17-retrieval-optimization.md)
18. [Storage](18-storage.md)
19. [Caching](19-caching.md)
20. [Scripts and CLI](20-scripts-and-cli.md)
21. [Testing](21-testing.md)
22. [Setup](22-setup-guide.md)
23. [Execution](23-execution-guide.md)
24. [Error handling](24-error-handling.md)
25. [Operational runbook](25-operational-runbook.md)

Architecture diagrams are collected in [diagrams/](diagrams/).

## Important implementation boundaries

- The inspected application is currently a collection of Python modules and service classes, not a complete runnable web API.
- `main.py` is a greeting/placeholder entry point; `app/main.py` currently prints `hi`.
- `app/api/v1`, `app/guardrails`, `app/memory`, `app/observability`, `app/schemas`, `app/tasks`, `app/tools`, and `app/utils` contain no implementation files in the reviewed tree.
- `migrations/` is empty. SQLAlchemy metadata creation is provided by the database helper and scripts.
- This review did not execute the full test suite or contact external services. Runtime behavior described here is derived from source and tests.
- The project contains sample PDFs and a local SQLite BM25-related data file under `data/`; treat these as fixtures or local artifacts, not production data.

## Source-of-truth policy

When code and this documentation disagree, the code is authoritative. Update the relevant page when behavior changes. Document uncertainty explicitly rather than inferring undocumented behavior.
