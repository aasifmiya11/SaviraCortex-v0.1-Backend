# Retrieval Flow

The diagram reflects the current retrieval orchestrator: PostgreSQL-derived authorization catalogue, summary-based candidate generation, candidate-scoped chunk search, global fusion/reranking and adaptive query expansion.

```mermaid
flowchart TD
 Q[User query] --> A[AuthorizationService]
 A --> C[Authorized active/superseded catalogue]
 C --> M[Multi-query LangGraph]
 M --> S[Summary similarity search]
 S --> V[Validate against authorized version allowlist]
 V --> D[Dense chunk retrieval]
 V --> L[Qdrant BM25 chunk retrieval]
 D --> F[Global RRF fusion]
 L --> F
 F --> R[Cross-encoder reranking]
 R --> K[Adaptive score selection]
 K --> T{At least k_min qualify?}
 T -->|Yes| O[Return selected chunks and provenance]
 T -->|No, rounds remain| E[Generate additional queries from prior queries and retrieved chunks]
 E --> S
 T -->|No rounds remain| O
```

The current orchestrator calls `AuthorizationService` directly; the separate Redis authorization cache helper is not wired into this path.
