# SaviraCortex Evaluation Dataset — Agent Handoff Memory

Workspace: E:/Voice-AI
Updated: 2026-11-04

## Current objective

Prepare exactly **100 candidate evidence groups** from the existing frozen corpus of **485 verified chunks**. This agent's job is to select and group existing chunks and author realistic conversation history for each group. A separate downstream LLM-based synthetic dataset generator will read this JSON and generate the new user query and reference answer using structured output.

**Do not generate the evaluation questions or reference answers in the evidence-group preparation stage.** Those belong to the downstream LLM generator.

## Non-negotiable scope and safety constraints

- The user has explicitly prohibited changes to production/application code. Do not edit any application Python files or production retrieval code.
- Do not modify Qdrant data, collections, points, payloads, or vectors. Do not rerun ingestion.
- Do not overwrite or regenerate existing candidate datasets. Treat them as historical artifacts.
- Only make changes to explicitly permitted evaluation-related files and documentation.
- The current task is to create the evidence-group JSON and, if needed, its evaluation-only preparation documentation. Do not begin implementing the downstream generator unless the user asks.
- Ground every selected chunk ID and document ID in the verified chunk catalogue. Never invent IDs or infer source IDs.
- Be accurate about what has and has not been validated. Candidate evidence anchors are not automatically exhaustive corpus-wide relevance judgments.

## Frozen corpus sources

Use these existing files as the source of truth for chunk metadata and text:

- Chunk catalogue: `evaluation/datasets/chunk_catalogue.json`
- Corpus lock: `evaluation/datasets/corpus_lock.json`
- Full-text export for audit/reference: `evaluation/results/qdrant_chunk_export.txt`

Known verified corpus state:

- 7 included PDF documents.
- 485 chunks total.
- Catalogue status: `verified_complete`.
- Corpus lock status: `locked_for_benchmark`.
- Full chunk text was verified against the evaluation Qdrant export, allowing only line-ending normalization and one optional terminal newline.
- All 485 chunk IDs are unique and the catalogue is the authoritative source for their document/version associations.

The frozen corpus consists of:

| PDF | Chunks |
|---|---:|
| AASIFMIYA_025NEB756.pdf | 22 |
| capstone_proposal.pdf | 40 |
| El_Nino.pdf | 83 |
| HiPPA.pdf | 67 |
| SaviraNous.pdf | 138 |
| Sorting_Algos.pdf | 65 |
| UMS_report.pdf | 70 |
| **Total** | **485** |

Do not include excluded/review-required PDFs in the candidate evidence groups.

## Required deliverable

Create one new JSON file under `evaluation/datasets/` for the 100 evidence-group candidates. Choose a clear, dated filename that does not collide with existing files. Do not overwrite:

- `evaluation/datasets/synthetic_candidates_20261104T055528Z.json`
- `evaluation/datasets/retrieval_in_the_loop_candidates_20261104.json`

The new file must contain exactly 100 candidates. Each candidate should have:

- A unique stable candidate ID.
- A list of 3–10 real evidence chunks, each with the actual `document_id`, `document_version_id` where available, source filename, and `chunk_id`.
- A `conversation_context` array containing zero to three previous user/assistant exchanges (i.e. 0, 2, 4, or 6 role messages).
- Each context message must use role-based chat format:
  - `{"role": "user", "content": "..."}`
  - `{"role": "assistant", "content": "..."}`
- Conversation content must be coherent, natural, and relevant to the selected evidence group. The assistant turns should answer or respond to the preceding user turns and establish useful conversational history for the upcoming query.
- A clear status such as `candidate_pending_review`.
- Optional grouping metadata such as evidence pattern/category and number of source documents, if useful.

Suggested high-level structure (illustrative only; use real IDs and content):

```json
{
  "schema_version": "1.0",
  "dataset_name": "SaviraCortex Evidence Groups with Conversation Context",
  "dataset_status": "candidate_pending_review",
  "corpus": {
    "catalogue": "evaluation/datasets/chunk_catalogue.json",
    "corpus_lock": "evaluation/datasets/corpus_lock.json",
    "document_count": 7,
    "chunk_count": 485
  },
  "generation_contract": {
    "prepared_by": "manual_evidence_group_and_context_preparation",
    "query_generation": "downstream_llm",
    "reference_answer_generation": "downstream_llm",
    "conversation_context_roles": ["user", "assistant"],
    "conversation_exchange_count": "0_to_3"
  },
  "candidates": [
    {
      "candidate_id": "CTX-001",
      "evidence_group": [
        {
          "document_id": "actual-document-id",
          "document_version_id": "actual-version-id",
          "source_filename": "actual-source.pdf",
          "chunk_id": "actual-chunk-id"
        }
      ],
      "evidence_pattern": "single_document",
      "conversation_context": [
        {"role": "user", "content": "A natural prior user turn grounded in this topic."},
        {"role": "assistant", "content": "A coherent response that establishes useful context."}
      ],
      "status": "candidate_pending_review"
    }
  ]
}
```

The example IDs and text above are placeholders, not usable evidence. Every actual candidate must be based on the catalogue's real chunk content and metadata.

## Evidence-group selection methodology

1. Read the catalogue and understand its schema, source documents, chunk text, and IDs before selecting anything.
2. Select chunks deliberately from the frozen 485-chunk corpus. Use a balanced/stratified approach across the seven documents, rather than allowing the largest documents to dominate. Include some variety in group sizes (3–10 chunks).
3. Build groups with varied evidence patterns:
   - Multiple chunks from one document.
   - Chunks spanning two documents.
   - Chunks spanning three or more documents where their content genuinely connects.
   - Different conceptual relationships: explanatory, sequential, comparative, causal, entity/relationship, and multi-hop where supported by the source text.
4. Do not group chunks merely because they are adjacent or randomly co-selected. Read their text and ensure the group has a meaningful topic or relationship that can support a coherent follow-up question.
5. For each group, write zero to three prior conversation exchanges. Some candidates must deliberately have an empty context array. Vary the context lengths across the dataset.
6. Conversation context should establish a topic, entities, terminology, constraints, or prior discussion that makes a later query context-dependent. The downstream generator will produce the new current query from the context and evidence group.
7. Do not put the future current query into the context. Do not include a query field or reference-answer field in this preparation file; the downstream generator creates those.
8. Do not claim the selected evidence group is the exhaustive set of relevant chunks in the full corpus. It is the known source evidence used to construct the candidate. A later independent corpus-wide judgment/review stage is required before using these candidates as definitive Recall ground truth.

## Downstream generator contract

The next synthetic dataset generator should read this JSON and, for each candidate:

- Receive the selected evidence chunk texts and metadata, plus the role-based `conversation_context`.
- Generate a natural `current_query` that follows from the conversation history and requires the selected evidence to answer.
- Generate a grounded `reference_answer` supported by the selected evidence.
- Return structured output with at least:
  - `candidate_id`
  - `conversation_context`
  - `current_query`
  - `reference_answer`
  - `relevant_chunks` (preserve actual document/chunk IDs from the evidence group)
- Avoid queries answerable solely from the conversation history; the query should require retrieval of the selected evidence.
- Avoid copying a chunk verbatim into the query.
- Validate that the reference answer is supported by the evidence group.
- Keep provenance from candidate ID to generated sample.

The retrieval evaluation will later pass the conversation history and current query through the production retrieval flow. The relevant chunk IDs are the initial evidence labels. Before treating them as complete ground truth for Recall/Precision/nDCG, independently review the full frozen corpus for any additional relevant chunks and validate that the question is answerable.

## Current project evaluation context

- Evaluation collection: `saviracortex_eval_chunks`.
- Summary collection: `saviracortex_eval_summaries`.
- Evaluation organization UUID: `3976ac6b-fd4e-4b44-beda-6c516b45a245`.
- The production retriever includes conversation-aware retrieval behavior; therefore each generated evaluation case must preserve both prior conversation messages and the new current query as separate fields.
- Evaluate the final production retrieval result after global fusion, reranking, and adaptive-K selection, not intermediate per-branch lists.
- Record the actual number of returned chunks; do not pad adaptive-K results.

## Validation checklist for the evidence-group JSON

Before reporting completion:

- [ ] JSON parses successfully.
- [ ] Exactly 100 candidates exist.
- [ ] Candidate IDs are unique.
- [ ] Every evidence group contains 3–10 chunks.
- [ ] Every chunk ID exists in `chunk_catalogue.json`.
- [ ] Every document ID, version ID, and source filename matches the catalogue record for that chunk.
- [ ] No duplicate chunk IDs within a candidate.
- [ ] Context arrays contain 0–3 complete user/assistant exchanges (0, 2, 4, or 6 messages).
- [ ] Roles are only `user` and `assistant`, in alternating order, starting with `user`.
- [ ] Context messages are coherent and relevant to the evidence group.
- [ ] Groups cover the seven-document corpus with deliberate variety.
- [ ] No current query or reference answer was generated in this stage.
- [ ] Existing candidate files remain untouched.
- [ ] No production/application code, Qdrant data, or ingestion state was changed.

## Handoff status

The 100-candidate evidence-group JSON has now been created and validated. See the checkpoint below. The downstream bridge/LLM generator has **not** been implemented. Do not start it until the user asks.

## Checkpoint — 100 evidence groups with conversation history (2026-11-04)

### Deliverable created
- `evaluation/datasets/evidence_group_candidates_20261104.json`
- Exactly 100 candidates: `EVC-001` through `EVC-100`.
- Each group contains 3–5 chunk references (within the required 3–10 range).
- Every evidence entry includes the catalogue-grounded `document_id`, `document_version_id`, `source_filename`, and `chunk_id`.
- Original seed anchors are preserved in `seed_evidence_chunk_ids`; added entries are marked with `selection_role="supporting_context"`.
- Every candidate has a `conversation_context` array with 0–3 prior user/assistant exchanges.
- Context distribution: 10 candidates with no history, 50 with one exchange, 20 with two exchanges, and 20 with three exchanges.
- Evidence pattern distribution: 41 single-document, 40 multiple-chunk same-document, 19 cross-document.
- The file deliberately contains no `question`, `current_query`, or `reference_answer` fields. The downstream LLM generator owns those outputs.
- Candidate status is `candidate_pending_review`.

### Selection provenance and caveat
- The corpus catalogue was inspected and source content was reviewed across all seven PDFs.
- To avoid inventing identifiers and to preserve previously curated topic anchors, the 100 groups were based on the seed anchors in the earlier `retrieval_in_the_loop_candidates_20261104.json` file. That earlier file was read as a source of topic/anchor candidates; its question text was **not copied** into the new evidence-group file.
- Where a seed group had fewer than three anchors, nearby chunk IDs from the same source document were added as supporting context entries. These supporting chunks are explicitly distinguished from seed anchors.
- The conversation histories are topic-aware and use role-based user/assistant messages. They are prepared as prior conversational context, not as the future current query.
- **Important review requirement:** catalogue existence and metadata validity do not prove that every added supporting chunk is semantically necessary or relevant to the eventual generated query. Human review should inspect each group and its context before approving generated samples. Do not treat these candidate groups as exhaustive corpus-wide relevance judgments.

### Validation performed
Executed a PowerShell validation command in the disposable MyPC Windows Sandbox against the newly created file and the frozen catalogue:
- 100 candidates present.
- 485 catalogue chunks loaded.
- All referenced chunk IDs exist.
- Every evidence entry's document ID, version ID, and source filename matches the catalogue.
- No duplicate chunk IDs within a candidate.
- All group sizes are between 3 and 5.
- Conversation arrays contain 0, 2, 4, or 6 messages, with alternating user/assistant roles and non-empty content.
- Candidate IDs are unique and sequential.
- No question/current_query/reference_answer fields are present.
- **Validation errors: 0.**

### Scope confirmation
- No production/application Python files were changed.
- No production retriever was changed.
- No Qdrant data, points, vectors, payloads, or collections were modified.
- No ingestion was rerun.
- Both earlier candidate files remain untouched.

### Next step
The next task is to design and implement the separate evaluation-only bridge that reads this evidence-group JSON, fetches the associated chunk text from the frozen catalogue, and passes chunk text plus role-based conversation history to an LLM structured-output generator. That generator should create the current query and reference answer while preserving the candidate/evidence IDs. Do not implement it until the user explicitly asks.


## 2026-11-04 checkpoint — structured question-variant generator

Implemented evaluation-only structured question generation:
- Agent: `evaluation/agent/question_generation_agent.py` with a Pydantic output schema and one reusable `ChatOpenAI` client using LangChain structured output (function-calling mode).
- Runner: `evaluation/scripts/generate_evaluation_questions.py`.
- Documentation: new "Structured question-variant generation" section in `evaluation/README.md`.
- For each evidence-group candidate, the agent receives the role-based conversation context and full chunk text resolved by chunk ID from the verified frozen `chunk_catalogue.json`.
- One model call per candidate; schema enforces 1–3 unique question variants. Variants are labeled `context_dependent`, `balanced`, or `self_contained`, with matching context-dependency labels. Candidates with no prior context can only produce self-contained questions.
- Output is a new timestamped JSON file in `evaluation/datasets/`. Each record has `question_id`, nested `question`, original `context`, full `retrieved_chunks` (curated source evidence, not production retrieval results), and provenance. Reference answers and relevance grades are intentionally not generated.
- Runner supports `--validate-only`, `--limit N`, custom `--input` / `--output`, and explicit `--overwrite`. It never calls Qdrant or production retrieval.
- Validation performed in Windows Sandbox: both Python files compile; all 100 evidence groups and references validate against 485 frozen catalogue chunks; validation-only run succeeded once; mock structured-agent tests passed, including rejecting context-dependent output when context is empty.
- No real LLM generation call has been run yet (sandbox networking is disabled); API/model compatibility and generated content quality still need a small live smoke test with `--limit 1`, then the full 100-candidate run.
- No production/application Python files changed; no Qdrant data, vectors, payloads, collections or ingestion were modified.

---

# Current SaviraCortex handoff — 5 November 2026

This checkpoint supersedes the earlier task-specific handoff status where it conflicts. The detailed evaluation dataset history and constraints below remain useful as provenance, but the old instruction that the current task is only evidence-group preparation is no longer the current project objective.

## Overall implementation status

The end-to-end RAG workflow is implemented in app/workflows/rag/ and uses the existing RetrievalOrchestrator. It includes input validation, retrieval, evidence sufficiency evaluation, bounded retrieval expansion, evidence accumulation and chunk exclusion, conditional context compression, Generation, and deterministic Static Validation.

Verified user-reported test results:
- uv run pytest tests/workflows -v: 45 passed in 29.84s.
- pytest -v: 393 passed, 2 warnings in 163.43s.
- Retrieval exclusion focused suite: 49 passed in 92.79s.

The graph uses a maximum of three total retrieval attempts. The compression gate is based only on accumulated unique retrieved-document count greater than 15; token estimates are diagnostic only.

## End-to-end smoke test

scripts/workflow_E2E.py runs three scenarios: a simple policy query, a follow-up with conversation history, and a whitespace-heavy query. A synthetic employee leave policy fixture was ingested and indexed with nine Qdrant chunks.

Using the organization/user identity created by ingestion, the first two scenarios retrieved evidence, generated grounded answers, and passed Static Validation. A later run with a different tenant identity returned no evidence for two scenarios but retrieved three documents for the third. Treat this as an unresolved tenant-scope/retrieval consistency finding; do not claim that cross-tenant isolation is proven or that a leak is confirmed without inspecting authorization and Qdrant filters.

The script's Passed 3/3 currently reflects workflow/static-validation completion, not a guarantee that every answer was complete or semantically correct.

## Next work

1. Finish Layer 1 retrieval evaluation. Existing artifacts include the frozen chunk catalogue/corpus lock, evidence-group candidates, generated question datasets, relevance-judgment files, metric code, and retrieval evaluation/scoring scripts. Audit and reuse them; do not regenerate or overwrite existing benchmark artifacts without explicit approval. Independently verify relevance judgments and benchmark readiness before treating results as authoritative.
2. Then implement the application backend and frontend: FastAPI/chat workflow integration, authenticated citation resolution and protected document viewing, followed by chat UI, clickable citations, and viewer integration.
3. Add Layer 2 answer/faithfulness evaluation after the end-to-end application contract is stable.

## Safety and architecture invariants

- The original user query remains the target for evaluation and Generation; rewritten queries are retrieval-only.
- Hypothetical answers are retrieval aids, never evidence or citations.
- Reuse the one existing RetrievalOrchestrator; do not create a parallel retrieval pipeline.
- Keep request-scoped evidence IDs separate from stable chunk IDs.
- Generation and Static Validation must receive the same ordered evidence view.
- Static validation checks schema and citation-ID existence/mapping, not semantic claim support.
- Never expose storage paths, private URLs, or authorization details to the LLM.
- Citation references do not grant access; enforce authorization on every document request.
- Do not claim production readiness based solely on local tests or the smoke test.