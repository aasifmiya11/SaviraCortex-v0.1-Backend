# 9. Document Ingestion

## Orchestrator

`DocumentIngestionService` in `app/services/document_ingestion/ingestion_service.py` coordinates PDF validation, extraction, normalization, hashing, summary generation, duplicate matching, object upload, registration and transaction cleanup. Collaborators are injected (validator, loader, hash service, sampler, summarizer, storage, session factory, matching and registration factories), which allows tests to substitute fakes.

## Workflow

```mermaid
sequenceDiagram
 participant C as Caller
 participant I as IngestionService
 participant P as PDF pipeline
 participant A as Summarizer
 participant M as Matching
 participant B as B2 storage
 participant D as Registration/DB
 C->>I: ingest_pdf(path, organization_id)
 I->>P: validate and extract
 P-->>I: page documents
 I->>I: normalize, validate text, hash
 I->>A: summarize sampled pages
 A-->>I: document metadata and summary
 I->>M: exact and semantic matching
 alt exact duplicate
 M-->>I: duplicate outcome
 I-->>C: duplicate
 else potential match
 M-->>I: review required
 I-->>C: review_required
 else no match
 I->>B: upload original PDF
 I->>D: register pending version
 D-->>I: registration result
 I-->>C: registered_pending
 end
```

## Outcomes

| Outcome | Meaning | Upload/register |
|---|---|---|
| `duplicate` | Exact file or normalized content match | No |
| `review_required` | Potential semantic/summary match requires review | No |
| `registered_pending` | No match; file stored and pending version registered | Yes |

The organization identifier is validated as a UUID. Extracted pages are normalized before sampling; page metadata is retained; the original PDF is uploaded, not a rewritten PDF. Tests exercise stable organization-scoped duplicate lock keys.

## Failure and cleanup

If upload or registration fails, the service rolls back and attempts object cleanup when applicable. Cleanup errors are retained alongside the primary ingestion failure. Tests cover upload failure, registration failure and cleanup failure.

The tests exercise result fields such as status, filename, file hash, content hash, page count, storage key and optional registration result. The service is not exposed by an implemented HTTP route in the reviewed repository.
