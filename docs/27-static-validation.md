# 27. Static Validation and Citation Mapping

**Status:** implemented; all 6 Static Validation tests passed as part of the combined 17-test run reported on 4 November 2026.

## Purpose

The Static Validation Layer is a deterministic backend component. It does not call an LLM. It validates Generation Agent output, checks request-scoped citation IDs, applies basic status/citation consistency rules, and maps cited IDs to an allowlisted subset of metadata from the original retrieval candidates.

It does not perform retrieval, reranking, answer generation, semantic claim-to-source verification, document access, storage access, URL generation, or HTTP routing.

## Files

| File | Responsibility |
|---|---|
| `app/validation/__init__.py` | Public exports |
| `app/validation/schemas.py` | `CitationReference` and `GenerationValidationResult` |
| `app/validation/generation_validator.py` | Validation and citation registry logic |
| `tests/agent/test_generation_validation.py` | Validation unit tests |

## Input contract

The public entry point is:

```python
result = static_validation_layer.validate_generation_output(
    output=generation_output,
    retrieved_documents=selected_candidates,
)
```

`output` accepts a `GenerationOutput` instance or a compatible dictionary. `retrieved_documents` must be the same ordered candidate list supplied to Generation Agent. Candidates are dictionaries with `page_content` and `metadata`.

Candidates with blank or non-string content are skipped, matching Generation Agent evidence preparation. Remaining candidates are assigned `E1`, `E2`, and so on. The list must not be reordered or reconstructed between generation and validation: evidence IDs depend on candidate order.

A candidate that is not a dictionary, or has non-dictionary non-empty metadata, results in failed validation.

## Deterministic checks

- Parse or accept the existing `GenerationOutput` schema.
- Require citation IDs to match `E[1-9][0-9]*`.
- Require each cited ID to exist in this request's evidence registry.
- Reject citations on an `insufficient_evidence` response.
- Report a warning, rather than an error, when an `answered` or `partial` response has no citations.

These checks do not prove that a cited passage supports the associated claim. Semantic faithfulness is outside this component.

## Citation metadata mapping

Only cited IDs are returned. The current allowlist is:

| Result field | Candidate metadata source |
|---|---|
| `evidence_id` | Assigned using Generation evidence ordering |
| `document_id` | `metadata.document_id` |
| `document_version_id` | `metadata.document_version_id` |
| `document_title` | First available of `document_title`, `source_filename`, or `source` |
| `page` | `metadata.page` |
| `section` | First available of `section_heading` or `section` |

`CitationReference` forbids extra fields. Storage keys, bucket names, object paths, signed URLs, permission details, retrieval scores, embeddings, and arbitrary candidate metadata are not returned.

## Output contract

`GenerationValidationResult` contains:

| Field | Meaning |
|---|---|
| `is_valid` | Whether deterministic validation passed |
| `output` | Parsed `GenerationOutput`, or `None` if schema parsing failed |
| `errors` | Deterministic validation failures |
| `warnings` | Non-fatal conditions |
| `citations` | Trusted metadata for cited IDs |

When any validation error exists, the current implementation returns an empty citation list. A result can be valid while containing warnings, such as an answer without citations.

## Relationship to Generation Agent

Generation Agent remains responsible for prompt evidence preparation, model invocation, structured parsing, and citation-ID existence checks on its sync, async, and streaming completion paths. Its `validate_citations()` method delegates the ID check to `static_validation_layer.validate_citation_ids()` and preserves the existing `CitationValidationError` interface.

`validate_generation_output()` is the broader post-generation operation. The caller must pass the original ordered candidate list used for generation.

## Clickable citations: future responsibility split

1. Generation Agent emits answer segments containing IDs such as `E1`.
2. Static Validation checks those IDs and maps them to trusted document/version/page metadata.
3. A future citation resolver uses trusted identifiers to resolve a viewer route.
4. A future API layer exposes document-viewing operations.
5. The frontend renders citation markers as clickable controls.
6. The document viewer checks the current user and document permissions on every open.

The validator deliberately does not return URLs. The LLM must not generate API URLs, storage paths, or permission decisions. An evidence ID is a reference, not a permission grant.

At the time of this documentation, `app/api/v1/endpoints` has no endpoint implementation and `app/main.py` is a placeholder, not a running FastAPI application. No API route, citation resolver, or viewer endpoint was added by the validation implementation.

## Tests and verification

`tests/agent/test_generation_validation.py` covers successful metadata mapping, unknown citation rejection, malformed output, citations on insufficient-evidence output, missing-citation warnings, and evidence ordering when blank chunks are skipped.

The user ran the combined command on 4 November 2026:

```powershell
uv run pytest tests/agent/test_generation.py tests/agent/test_generation_validation.py -v
```

Reported result: **17 passed in 6.14 seconds** — 11 Generation Agent tests and 6 Static Validation tests. This verifies these two focused test modules only; it is not a full-suite or production integration result.

## Limitations and next steps

- Semantic claim-to-source verification is not implemented.
- Citation mapping depends on preserving the original evidence order.
- Missing source metadata remains missing; the validator does not infer it.
- API routing, protected document delivery, page navigation, and frontend citation rendering are future work.
- A future resolver must use trusted document identifiers and check permissions on every document request.

Recommended order: integrate the layer through the end-to-end LangGraph workflow while preserving the original ordered retrieval candidates; implement a citation resolver using existing repository and permission-service contracts; establish the FastAPI entry point and router; implement protected document viewing; then add frontend citation rendering. See [Remaining implementation roadmap](28-remaining-implementation-roadmap.md).
