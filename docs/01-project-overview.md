# 1. Project Overview

## 1.1 Purpose

Voice-AI is a Python codebase for ingesting PDF documents, extracting and normalizing their text, identifying duplicates or related documents, registering document versions, indexing content, and retrieving relevant passages under organization-scoped access rules.

Although the repository is named Voice-AI, the inspected implementation is primarily a document-processing and retrieval backend. The reviewed code does not demonstrate speech recognition, audio generation, or a conversational voice interface.

## 1.2 Main capabilities present in code

- Validate PDF files and determine page counts.
- Extract native PDF text and use OCR when needed.
- Normalize extracted text and preserve page metadata.
- Calculate file and normalized-content hashes.
- Generate structured document summaries and metadata with an LLM agent.
- Compare incoming documents with existing records using exact hashes and summary-based matching.
- Register documents and versions as pending.
- Store original PDF files in Backblaze B2 through an S3-compatible client.
- Split extracted pages into chunks, create embeddings, and index chunks in Qdrant.
- Store document-level summaries in a separate Qdrant collection.
- Maintain document/version lifecycle state in a relational database.
- Apply organization, membership, role, department, and document ACL rules.
- Generate multiple query formulations and perform candidate-scoped hybrid retrieval.
- Fuse result rankings, rerank candidates, and adapt retrieval depth.

## 1.3 Primary workflows

### Ingestion workflow

A PDF is validated, extracted, checked for usable text, normalized, hashed, sampled for summarization, matched against existing documents, and then either treated as a duplicate, routed for review, or uploaded and registered as a pending version.

### Indexing workflow

A pending version is loaded from object storage, verified/processed, chunked and embedded, indexed in Qdrant, represented in the summary collection, and activated in the relational database. External vector-store lifecycle synchronization is coordinated around the database activation.

### Retrieval workflow

The retrieval service obtains an authorized document scope and catalogue, expands the user's query, creates candidate document/version constraints, runs dense and lexical retrieval, combines rankings, reranks results, and returns selected chunks with metadata.

## 1.4 Actors and boundaries

The code models organizations and users, but the inspected tree does not provide a complete HTTP authentication or API layer. Services receive organization and user identifiers from their callers. Integrating authentication and exposing endpoints remain application-level responsibilities outside the currently implemented modules.

## 1.5 Non-goals and unverified assumptions

Do not infer from dependency declarations that every dependency is actively used. Do not infer that the system is deployed, that external services are configured, or that all integration tests pass. The code review did not establish a production deployment topology, user interface, audio pipeline, or background worker runtime.

## 1.6 Key source locations

- Ingestion: `app/services/document_ingestion/ingestion_service.py`
- Indexing: `app/services/document_indexing/`
- Retrieval: `app/services/retrieval/retrieval_service.py` and `app/rag/retrieval/`
- Models: `app/models/`
- Authorization: `app/services/authorization/` and `app/repositories/authorization_repository.py`
- Storage: `app/storage/` and `app/rag/vector_stores/`
