# Synthetic Golden Dataset Generation Approach

## 1. Objective

Create a reproducible synthetic evaluation dataset for SaviraCortex using DeepEval's Synthesizer, while reusing the existing SaviraCortex document-extraction and normalization logic.

The selected workflow is document-based Golden generation through:

```python
Synthesizer.generate_goldens_from_docs(document_paths=[...])
```

DeepEval will handle its own chunking and context construction for synthetic data generation. SaviraCortex will continue to use its own chunking and retrieval pipeline when the generated dataset is evaluated.

## 2. High-level workflow

1. Select the source PDF documents for the evaluation corpus.
2. Pass each PDF through the reusable PDF loading, text extraction, normalization, and cleaning functionality from the existing SaviraCortex ingestion modules.
3. Capture the cleaned document content before the SaviraCortex chunking stage.
4. Write the cleaned content to temporary Markdown files. Prefer one Markdown file per source document so document boundaries and provenance remain clear.
5. Pass the temporary Markdown file paths to DeepEval's `generate_goldens_from_docs()`.
6. Configure DeepEval's context construction, including its chunking settings and minimum/maximum context length, as appropriate for the installed DeepEval version.
7. Use the project's custom DeepEval LLM adapter and Hugging Face embedding adapter during synthesis.
8. Serialize the generated Golden records into the canonical JSONL dataset, preserving relevant source-document provenance.
9. Verify that dataset serialization completed successfully.
10. Delete the temporary Markdown files only after successful dataset creation. If generation or serialization fails, retain the temporary files to support debugging.

## 3. Reuse ingestion functionality without coupling the pipelines

The evaluation module should import and reuse the existing ingestion components responsible for:

- Loading and extracting PDF content.
- Normalizing and cleaning extracted text.
- Retaining document identity and useful source metadata.

The evaluation workflow should access the cleaned content before the production ingestion chunking stage. It should not need to invoke production upload/download operations merely to prepare the Synthesizer inputs.

This keeps extraction and normalization consistent with SaviraCortex while allowing DeepEval to perform its own chunking for Golden generation.

The existing production ingestion and retrieval behavior should not be changed as part of this work.

## 4. Temporary Markdown inputs

Use temporary Markdown files as the interface between the ingestion components and DeepEval.

Recommended practices:

- Keep one file per source PDF rather than merging the entire corpus into one undifferentiated file.
- Preserve the source document name or a stable document identifier in the filename and/or document heading.
- Preserve page boundaries or page labels when the extraction output makes them available.
- Use clear Markdown headings and separators where needed.
- Keep a mapping from each temporary file to its original source document and metadata.

Example:

```text
evaluation/
├── source_pdfs/
├── temporary_documents/
│   ├── policy_document_a.md
│   └── handbook_document_b.md
└── datasets/
    └── synthetic_goldens.jsonl
```

The temporary directory is a runtime working area. The Markdown files are removed after successful Golden generation and dataset serialization; they are not the canonical dataset.

## 5. DeepEval Synthesizer configuration

Use the document-based method:

```python
goldens = synthesizer.generate_goldens_from_docs(
    document_paths=markdown_paths,
    ...
)
```

DeepEval is responsible for:

- Reading the Markdown documents.
- Splitting document content into its own chunks.
- Constructing and selecting contexts.
- Applying the configured minimum and maximum context-length constraints.
- Generating synthetic inputs and expected outputs (Goldens).

The exact chunking and context-construction parameters must be checked against the DeepEval version pinned by the project before implementation.

### Important distinction

There are two independent chunking paths:

| Purpose | Chunking owner |
|---|---|
| Synthetic question and Golden generation | DeepEval |
| Actual SaviraCortex RAG evaluation retrieval | SaviraCortex |

The two configurations do not have to be identical. DeepEval's contexts are used to create reference questions and answers; during evaluation, SaviraCortex retrieves its own chunks from the isolated evaluation Qdrant collection.

The document-based DeepEval workflow may use its own internal ChromaDB-backed context construction. This is separate from SaviraCortex's Qdrant collection. The context-based Synthesizer method is not being selected for this workflow.

## 6. Model integration

Reuse the model clients already present in SaviraCortex. Avoid adding an unrelated provider or a second independent model configuration.

### LLM

- Underlying client: existing LangChain `ChatOpenAI` client.
- DeepEval integration: a project-owned adapter extending `DeepEvalBaseLLM`.
- The adapter should expose the methods required by the installed DeepEval interface, including model loading, synchronous generation, asynchronous generation, and model-name reporting.
- It must support the structured/schema-based output required by the Synthesizer and selected metrics.

No MiniMax-specific configuration or provider-specific request parameters are part of this design.

### Embeddings

- Underlying client: existing Hugging Face embedding client used by SaviraCortex.
- DeepEval integration: a small project-owned adapter extending `DeepEvalBaseEmbeddingModel`.
- The adapter should implement the embedding interface required by the installed DeepEval version, including single-text and batch embedding, synchronous and asynchronous methods where required, model loading, and model-name reporting.
- Supply this adapter to the Synthesizer's context-construction configuration so DeepEval uses the existing Hugging Face embedding model for context selection/grouping.

The LangChain embedding client should not be assumed to be directly interchangeable with DeepEval's embedding interface; the adapter provides that boundary.

## 7. Dataset format and provenance

Use JSONL as the canonical dataset format: one Golden record per line. JSONL is suitable for nested context lists and additional provenance fields.

Preserve the native Golden fields provided by the installed DeepEval version, such as:

- `input`
- `expected_output`
- `context` (when present)

Add project-owned provenance separately, for example:

- Source document identifiers.
- Source document names.
- Page references, where available.
- Generation model identifier.
- Dataset/corpus version.
- Other source metadata needed to trace a Golden back to its input material.

Do not assume that DeepEval's Golden object automatically contains Qdrant chunk IDs or a field named `expected_retrieval_context`. Those are not interchangeable with the Golden's generation `context`. Preserve provenance explicitly in the project-owned serialization structure.

Keep dataset-level generation information in a companion metadata file when useful, including:

- Generation timestamp.
- DeepEval version.
- LLM identifier/configuration label.
- Embedding model identifier.
- Source corpus version.
- Relevant context-construction and chunking configuration.
- Number of source documents and generated Goldens.

## 8. Evaluation after Golden generation

Golden generation and RAG test execution are separate stages.

For evaluation:

1. Ingest the original evaluation PDFs through the SaviraCortex ingestion pipeline into an isolated evaluation Qdrant collection.
2. Load the generated Golden dataset.
3. Use each Golden's input as the test query.
4. Run the actual SaviraCortex retrieval and answer-generation workflow.
5. Construct DeepEval test cases using the actual answer and actual retrieved context, alongside the reference information available from the Golden and its preserved provenance.
6. Run the selected metrics.

The selected metrics are:

- Answer Relevancy
- Faithfulness
- Contextual Precision
- Contextual Recall
- Contextual Relevancy

No classical retrieval metrics such as Recall@K, Precision@K, MRR, or nDCG are part of the current evaluation plan.

The evaluation Qdrant collection is isolated from the normal application collection. DeepEval's internal document-context construction storage and SaviraCortex's evaluation Qdrant collection serve different purposes.

## 9. Failure handling and cleanup

Temporary Markdown files must not be deleted before the generated dataset has been successfully serialized and verified.

Expected behavior:

- If PDF extraction or normalization fails, report the affected source document.
- If Golden generation fails, retain temporary Markdown inputs for diagnosis.
- If JSONL serialization or validation fails, retain temporary Markdown inputs and report the failure.
- Delete temporary Markdown files only after successful dataset creation.
- Do not silently discard generated Goldens or overwrite an existing dataset without an intentional versioning/overwrite decision.

## 10. Current architecture decisions

- [x] Reuse existing SaviraCortex PDF extraction and normalization functions.
- [x] Capture cleaned content before the application's chunking stage.
- [x] Write one temporary Markdown file per source document.
- [x] Use DeepEval's `generate_goldens_from_docs()`.
- [x] Let DeepEval perform its own chunking and context construction.
- [x] Configure minimum and maximum context length using the supported DeepEval configuration.
- [x] Reuse the existing LangChain `ChatOpenAI` client through a custom `DeepEvalBaseLLM` adapter.
- [x] Reuse the existing Hugging Face embedding client through a custom `DeepEvalBaseEmbeddingModel` adapter.
- [x] Save generated Goldens in JSONL with explicit provenance.
- [x] Delete temporary Markdown inputs only after successful dataset serialization.
- [x] Keep actual RAG evaluation retrieval in an isolated SaviraCortex Qdrant collection.
- [x] Evaluate Answer Relevancy, Faithfulness, Contextual Precision, Contextual Recall, and Contextual Relevancy.

## 11. Implementation note

This document records the agreed approach; it does not prescribe or implement module names, function signatures, configuration values, or directory changes beyond the conceptual layout above. Before coding, inspect the existing ingestion module boundaries and the installed DeepEval version to confirm exact adapter interfaces and Synthesizer configuration names.
