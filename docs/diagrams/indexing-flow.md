# Indexing Flow

```mermaid
flowchart TD
 A[Pending version in PostgreSQL] --> B[Validate parent/version and metadata]
 B --> C[Download original PDF from B2]
 C --> D[Verify registered SHA-256]
 D --> E[Extract all pages]
 E --> F[Split, attach metadata and embed]
 F --> G[Upsert chunk vectors as pending]
 A --> H[Upsert summary point as pending]
 G --> I[Update page count and activate in PostgreSQL]
 H --> I
 I --> J[Commit PostgreSQL transaction]
 J --> K[Mark new chunks active]
 J --> L[Mark previous chunks superseded]
 J --> M[Upsert summary point as active]
 K --> N[Return sync status/errors]
 L --> N
 M --> N
 N --> O[Reconcile lifecycle projections if needed]
```

Before a confirmed commit, indexing failures attempt to remove newly written Qdrant chunks/summary and roll back PostgreSQL. The original B2 PDF is retained. If commit outcome is uncertain, external points are preserved. Post-commit synchronization failures are reported rather than rolling back the database activation.
