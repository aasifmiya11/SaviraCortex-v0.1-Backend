# SaviraCortex Retrieval Evaluation

## Directory layout

- `corpus/source_pdfs/`: original PDF files supplied for the evaluation corpus.
- `datasets/`: versioned, canonical retrieval benchmark datasets (questions, reference contexts, relevant document/chunk IDs and relevance grades).
- `config/`: evaluation-only configuration and run manifests. Keep secrets out of version control.
- `results/`: per-query retrieval outputs and raw metric results for each experiment.
- `reports/`: aggregate comparisons, charts and final evaluation reports.

## Current workflow

1. Add source PDFs to `corpus/source_pdfs/`.
2. Inspect PDF integrity and extraction quality before ingestion.
3. Ingest through the existing SaviraCortex registration/ingestion workflow using a controlled evaluation organization and user.
4. Generate and validate the canonical benchmark from the ingested corpus.
5. Run retrieval through the production authorization-aware retrieval path.

Do not place benchmark JSON files in the PDF ingestion folder or index the benchmark itself in Qdrant. The evaluation corpus should use a dedicated Qdrant collection and fixed evaluation identities; authorization must still be enforced by the existing pipeline.
