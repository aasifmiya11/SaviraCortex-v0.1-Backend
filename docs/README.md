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
- Six independently implemented agents currently live under `app/agents/`: Document Summarizer, Multi-query Generator, Evidence Sufficiency Evaluator, Retrieval Expansion, Context Compression, and Generation. The Evidence Evaluator is injected into its RAG workflow node; it evaluates evidence sufficiency and reports missing requirements but does not perform retrieval or answer generation. The Retrieval Expansion Agent is injected into its workflow node; it produces a targeted rewritten query and a hypothetical answer for retrieval guidance only, not factual evidence. The Context Compression Agent performs query-focused, one-to-one compression of accumulated retrieved candidates only when the configured estimated-token threshold is exceeded; it preserves candidate order and metadata while changing only `page_content`. The Generation Agent is injected into its workflow node; it creates a structured, company-grounded answer from the original query, the compressed context view when available, and optional conversation history.
- The summarizer, Evidence Evaluator, Retrieval Expansion Agent, Context Compression Agent, and Generation Agent are prompt/model/parser chains; the multi-query generator is the LangGraph workflow.
- The project contains sample PDFs and local data artifacts under `data/`; treat these as fixtures or local artifacts, not production data.

## Audit scope and verification limits

The audit compared the documentation set against the repository structure and source for the main configuration, database, authorization, PDF, agent, ingestion, registration, indexing, retrieval, storage and operational-script paths. The relevant documentation pages and diagrams were corrected where source behavior differed or required more precise explanation.

The focused Generation and Static Validation test modules were run on 4 November 2026 and reported 17 passing tests. The Evidence Evaluator unit and workflow tests were run on 5 November 2026 and reported 11 passing tests. Retrieval Expansion unit and workflow tests were run on 5 November 2026 and reported 14 passing tests. Generation workflow adapter tests have been run on 5 November 2026 and reported 3 passing tests. Static Validation workflow adapter tests have been added; their execution status is not asserted here. The full test suite was not executed, external services were not contacted, and no production deployment/recovery was performed. Runtime behavior that depends on external providers is documented from source and tests, not claimed as live-verified.

## Source-of-truth policy

When code and this documentation disagree, code is authoritative. Update the relevant page when implementation changes. Document uncertainty explicitly rather than inferring undocumented behavior.
