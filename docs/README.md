# Voice-AI Technical Documentation

**Documentation status:** source-to-documentation audit updated 5 November 2026  
**Repository:** `E:\\Voice-AI`  
**Review baseline:** 5 November 2026

This documentation describes the implementation present in the repository at the time of review. It is not a product specification and does not imply that planned or placeholder components are implemented. When code and documentation disagree, the implementation is authoritative.

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
10. [AI agents and LLM workflows](10-ai-agents.md)
11. [Duplicate detection](11-duplicate-detection.md)
12. [Document registration and version creation](12-document-registration.md)
13. [Document indexing](13-document-indexing.md)
14. [Version lifecycle](14-version-lifecycle.md)
15. [Retrieval architecture](15-retrieval-architecture.md)
16. [Candidate generation](16-candidate-generation.md)
17. [Retrieval optimization](17-retrieval-optimization.md)
18. [Storage](18-storage.md)
19. [Caching](19-caching.md)
20. [Scripts and command-line utilities](20-scripts-and-cli.md)
21. [Testing](21-testing.md)
22. [Setup guide](22-setup-guide.md)
23. [Execution guide](23-execution-guide.md)
24. [Error handling](24-error-handling.md)
25. [Operational runbook](25-operational-runbook.md)
26. [Generation pipeline](26-generation-pipeline.md)
27. [Static validation and citation mapping](27-static-validation.md)
28. [Remaining implementation roadmap](28-remaining-implementation-roadmap.md)
29. [Context compression](29-context-compression.md)

Architecture diagrams are collected in [diagrams/](diagrams/).

## Important implementation boundaries

- The inspected application is a collection of Python modules and service classes, not a complete runnable web API.
- Root `main.py` prints a greeting; `app/main.py` prints `hi`. Neither starts an application server.
- `app/api/v1`, `app/guardrails`, `app/memory`, `app/observability`, `app/schemas`, `app/tasks`, `app/tools`, and `app/utils` contain no implementation files in the reviewed tree.
- `migrations/` is empty. The current `scripts/create_tables.py` name is misleading: it invokes a destructive reset that drops and recreates registered SQLAlchemy tables after confirmation.
- The `DepartmentAccessPolicy` model is defined but is not imported by `app.models`' package initializer; it is therefore not registered by the current package import alone.
- Retrieval currently calls `AuthorizationService` directly; the separate Redis-backed `AuthorizationCacheService` is not wired into the retrieval orchestrator.
- Six independently implemented agents currently live under `app/agents/`: Document Summarizer, Multi-query Generator, Evidence Sufficiency Evaluator, Retrieval Expansion, Context Compression, and Generation. The Evidence Evaluator is injected into its RAG workflow node; it evaluates evidence sufficiency and reports missing requirements but does not perform retrieval or answer generation. The Retrieval Expansion Agent is injected into its workflow node; it produces a targeted rewritten query and a hypothetical answer for retrieval guidance only, not factual evidence. The Context Compression Agent performs query-focused, one-to-one compression of accumulated retrieved candidates when the LangGraph workflow has more than 15 accumulated unique documents; the count-based graph decision is the only activation gate. It preserves candidate order and metadata while changing only `page_content`; token estimates are diagnostic only. The Generation Agent is injected into its workflow node; it creates a structured, company-grounded answer from the original query, the compressed context view when available, and optional conversation history.
- The summarizer, Evidence Evaluator, Retrieval Expansion Agent, Context Compression Agent, and Generation Agent are prompt/model/parser chains; the multi-query generator also uses a small LangGraph workflow. The end-to-end RAG workflow is implemented in app/workflows/rag/graph.py and coordinates input validation, the existing RetrievalOrchestrator, evidence evaluation, bounded retrieval expansion, optional context compression, Generation, and Static Validation.
- The project contains sample PDFs and local data artifacts under `data/`; treat these as fixtures or local artifacts, not production data.

## Audit scope and verification limits

The audit compared the documentation set against the repository structure and source for the main configuration, database, authorization, PDF, agent, ingestion, registration, indexing, retrieval, storage and operational-script paths. The relevant documentation pages and diagrams were corrected where source behavior differed or required more precise explanation.

The user reported the following local verification on 5 November 2026: `uv run pytest tests/workflows -v` — 45 passed in 29.84 seconds; `pytest -v` — 393 passed with 2 deprecation warnings in 163.43 seconds; and the focused retrieval-exclusion suite — 49 passed in 92.79 seconds. A live smoke test was also run with `scripts/workflow_E2E.py` against configured services and a synthetic indexed PDF. These results do not constitute CI verification, production deployment, or proof of tenant isolation. See [Testing](21-testing.md) and [Remaining implementation roadmap](28-remaining-implementation-roadmap.md).

## Source-of-truth policy

When code and this documentation disagree, code is authoritative. Update the relevant page when implementation changes. Document uncertainty explicitly rather than inferring undocumented behavior.
