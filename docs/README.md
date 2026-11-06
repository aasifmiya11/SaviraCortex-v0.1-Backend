# SaviraCortex — Backend Technical Documentation

**Repository:** `E:\\SaviraCortex`  
**Documentation baseline:** 5 November 2026

This documentation describes the implementation present in the SaviraCortex repository at the time of the latest checkpoint. It is an engineering reference, not a product specification. Planned work and unverified assumptions are identified separately. When source code and documentation disagree, the implementation is authoritative.

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
30. [Current application checkpoint](30-current-application-checkpoint.md)

Architecture diagrams are collected in [diagrams/](diagrams/).

## Current application snapshot

The backend now includes a FastAPI application and versioned API routes for health, authentication, organization signup and department management. Firebase Authentication provides Email/Password, Google and Phone identity; Firebase Admin verifies ID tokens on the backend. PostgreSQL stores SaviraCortex users, organizations, memberships and departments.

The Next.js frontend contains a public homepage, login, registration and organization dashboard. The dashboard loads the authenticated profile and organization-specific departments and exposes department creation to owner/admin members.

The earlier document ingestion, indexing, retrieval, LangGraph RAG, generation and static validation components remain part of the backend architecture. The latest implementation and verification boundaries are recorded in [30-current-application-checkpoint.md](30-current-application-checkpoint.md).

## Important implementation boundaries

- A passing schema test is not proof of successful database persistence or endpoint integration.
- Firebase authentication proves an external identity; SaviraCortex must still resolve the UID to an application user and verify organization membership/role.
- Hiding a UI control is not authorization. The backend must enforce every organization and role check.
- The presence of a SQLAlchemy model does not prove that the live database schema is migrated.
- The current department form creates organization departments; it does not yet assign users to departments.
- The current frontend pages do not yet constitute a complete chat/citation/document-viewer experience.
- The previous retrieval E2E tenant-scope inconsistency remains an investigation item, not a confirmed vulnerability or a security pass.
- Local test results are recorded with the exact command and scope. They are not CI or production verification.

## Latest reported verification

On 5 November 2026 the user reported:

```text
python -m pytest tests/test_v1_department_schemas.py tests/test_v1_auth_schemas.py tests/services/test_auth_services.py -v
20 passed in 2.33s
```

Earlier RAG workflow and full-suite results are retained in [Testing](21-testing.md). No frontend build/lint or department endpoint integration result is claimed by this documentation update.

## Source-of-truth policy

When code and this documentation disagree, code is authoritative. Update the relevant numbered page and the current checkpoint when implementation changes. Record the command, environment and result for verification; document uncertainty rather than inferring behavior.
