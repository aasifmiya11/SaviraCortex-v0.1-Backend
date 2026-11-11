# SaviraCortex — Backend Technical Documentation

**Repository:** `E:\\SaviraCortex`  
**Documentation baseline:** 7 November 2026

This documentation describes the backend and its integration with the Next.js frontend. It is an engineering reference, not a product specification. Planned work and unverified assumptions are identified separately. When source code and documentation disagree, the implementation is authoritative.

## Start here

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
31. [Project-wide current state](31-project-wide-current-state.md)
32. [Conversation persistence and session architecture](32-conversation-persistence-architecture.md)
33. [Security guardrails architecture](33-security-guardrails-architecture.md) — agreed design for ingestion inspection, runtime input/JEV checks, retrieval trust boundaries and output safety.
34. [Guardrails architecture decisions](34-guardrails-architecture-decisions.md) — working decisions for multi-tenant input/output guardrails, JEV classification, topicality routing, policy enforcement and streaming safety.
35. [Conversation timelines](35-conversation-timelines.md) — persisted branching, regeneration, and timeline navigation.
36. [Image understanding in chat](36-image-understanding.md) — image attachments, private B2 storage, multimodal generation, and model capability configuration.

Architecture diagrams are collected in [diagrams/](diagrams/).

## Current application snapshot

SaviraCortex is an organization-aware document intelligence and RAG application. The backend exposes FastAPI routes for authentication, organizations, roles, memberships, departments, invitations, document ingestion, document management and generation. Firebase Admin verifies browser-issued Firebase ID tokens. PostgreSQL stores application and tenant records. Backblaze B2 stores source files; Qdrant stores chunk and summary vectors.

The Next.js frontend provides the public homepage, login/registration, organization dashboard, invitation acceptance and chat. The dashboard includes member/role/department administration, invitation workflows, document ingestion and a document library. See [31 — Project-Wide Current State](31-project-wide-current-state.md) for the current route inventory and capability boundaries.

## Important implementation boundaries

- A passing schema test is not proof of successful database persistence or endpoint integration.
- Firebase authentication proves an external identity; SaviraCortex must still resolve the UID to an application user and verify organization membership/role.
- Hiding a UI control is not authorization. The backend must enforce every organization and role check.
- The presence of a SQLAlchemy model does not prove that a live database schema is current.
- PostgreSQL, Qdrant and B2 do not share a distributed transaction; ingestion and deletion workflows require retry/reconciliation behavior.
- Browser progress state is not a durable background job queue.
- A generation request that accepts conversation history does not prove persistent conversation storage.
- The earlier retrieval tenant-scope investigation remains a separate security/testing concern; do not treat a smoke test as a security pass.
- Local test results are recorded with the exact command and scope. They are not CI or production verification.

## Verification policy

No tests were run as part of the 7 November 2026 documentation refresh. Historical test evidence is retained in [21 — Testing](21-testing.md) with its original scope. The current development workspace has uncommitted backend and frontend changes; see [31 — Project-Wide Current State](31-project-wide-current-state.md).

## Source-of-truth policy

When code and this documentation disagree, code is authoritative. Update the relevant subsystem page and the current checkpoint when implementation changes. Record the command, environment and result for verification; document uncertainty rather than inferring behavior. Never commit credentials, Firebase service-account files, tokens, private keys or private document contents.
