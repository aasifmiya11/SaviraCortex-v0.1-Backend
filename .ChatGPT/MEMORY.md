# Voice-AI ChatGPT Handoff Memory

Workspace: E:/Voice-AI
Updated: 2026-11-03

Work in bounded passes. Keep chat output under 1,900 words. If a pass becomes too large or risky, stop and update this file with verified progress, blockers, and next steps. Do not claim unverified changes or tests.

User approved completing the ingestion/retrieval audit and the authorization policy below.

## Agreed authorization policy
- Access is the union of applicable direct-user, assigned-role, and department grants.
- Users may belong to multiple departments and have multiple assigned roles.
- No role hierarchy or implicit role inheritance.
- A document assigned to HR is automatically accessible to all members of HR.
- Explicit denies at user, role, and department level override applicable allows.

## Current pass: inspection only, no code changes
The MyPC voice-ai profile is open, rooted at E:/Voice-AI. I inspected the root, app, tests, scripts, authorization repository/models, registration service, indexing orchestrator/service, and AdaptiveKSelector. No application files have been modified and no tests have been run.

## Confirmed source findings
1. OrganizationMembership currently has one nullable department_id and a unique constraint on (organization_id, user_id), so the model cannot represent multiple departments per user. Implement a real association-table/schema solution; do not patch only the query.
2. authorization_repository.py handles allows for direct user, assigned roles, and the single membership department. It only evaluates user-level deny; role and department denies are missing.
3. The authorization query does not include Document.department_id as an automatic allow based on department membership.
4. Owner/admin built-in membership roles bypass ACL checks in both authorization methods. Review this against intended behavior before changing; the stated deny rule says explicit deny overrides applicable allows.
5. DocumentRegistrationService._validate_version_data() does not reject an empty summary. The indexing orchestrator rejects an empty summary later, risking unusable pending versions.
6. DocumentIndexingOrchestrator downloads a PDF and checks only that it exists and is non-empty; it does not compare its SHA-256 to DocumentVersion.file_hash before extraction/indexing.
7. AdaptiveKSelector defaults k_min to 5; agreed default is 3. Targeted tests are in tests/rag/retrieval/test_adaptive_k_selector.py.
8. RetrievalOrchestrator._empty_response() hardcodes expansion.stop_reason to no_authorized_document_versions for every empty-response reason.
9. Existing indexing code has compensating cleanup and Qdrant lifecycle sync flags. Preserve PostgreSQL as the lifecycle source of truth.

## Next bounded pass
1. Inspect membership/department relationships, model imports, schema creation/migration path, fixtures, and all references to OrganizationMembership.department_id and DepartmentAccessPolicy.
2. Implement multi-department association with migration/backfill if applicable.
3. Implement union grants (user, roles, department ACLs, document.department_id automatic grant) and deny precedence (user, role, department). Preserve organization scoping, archived exclusion and active/superseded catalogue semantics.
4. Add repository tests for multiple departments, grant union, auto-department grant, and each deny overriding an allow. Decide and test owner/admin deny behavior based on existing intended privilege semantics.
5. Validate non-empty summary at registration; verify downloaded PDF SHA-256 before extraction; add tests.
6. Set AdaptiveKSelector default k_min=3 and fix the empty-response stop reason; add tests.
7. Inspect OCR quality fallback/config wiring, exact-hash short-circuit, page-number helper, numeric validation, and lifecycle reconciliation. Keep scope bounded.
8. Run relevant tests via MyPC Windows Sandbox command on its disposable workspace copy. Record exact commands/results; do not imply source modifications from sandbox tests.
9. Update this file at every checkpoint. Freeze ingestion/retrieval only after verification; evaluations follow.

## Architecture invariants
- PostgreSQL is authoritative for the authorized document-version catalogue and lifecycle.
- Candidate generation starts from authorized catalogue versions; Qdrant applies organization/version allowlists before top-K.
- Validate candidates after summary retrieval; constrain chunk retrieval to candidate version IDs.
- Dense and BM25 share version constraints; global fusion deduplicates version-aware chunk identities; cross-encoder reranks globally fused candidates.
- Preserve org UUID consistency, document identity across versions, version UUID consistency across PostgreSQL/Qdrant, one-based page numbers, and chunk identity document_version_id + chunk_index.
- Do not introduce SPLADE, another vector DB, a new orchestration framework, or intermediate extraction storage without user approval.


## Checkpoint — authorization implementation pass (2026-11-03)

### Changes made in the workspace
- Added `app/models/organization_department_memberships.py` with a composite-key association table for multiple departments per organization member.
- Registered the association model in `app/models/__init__.py`.
- Retained `OrganizationMembership.department_id` as a legacy single-department field for backward compatibility. Authorization queries union it with the new association table.
- Updated `app/repositories/authorization_repository.py`:
  - union of direct user, assigned custom role, and all assigned department ACL allows;
  - automatic allow when `Document.department_id` matches one of the user's departments;
  - explicit user, role, or department deny overrides any of those grants;
  - owner/admin retain implicit organization-wide allow, but matching explicit denies still override it;
  - same predicates are shared by authorized document IDs and authorized version catalogue queries;
  - archived documents remain excluded and catalogue versions remain limited to active/superseded.
- Updated the partial unique ACL indexes in `app/models/document_acl.py` so `effect` is part of the uniqueness key. This permits an allow and deny for the same principal/document pair.
- Added PostgreSQL migration `migrations/20261103_multi_department_authorization.sql`:
  - creates the department-membership association table;
  - backfills existing non-null `organization_memberships.department_id` rows idempotently;
  - replaces the ACL partial unique indexes to include effect.
- Removed the unused `DepartmentAccessPolicy` model from active `app.models` registration/exports. Its source file remains for historical reference; repository-wide source scan found no active consumers beyond the old model registration.
- Added `tests/test_authorization_repository.py` with coverage for union grants, legacy and multi-department memberships, document-department auto-grants, user/role/department deny precedence, same-principal allow+deny, owner deny precedence, and no-access behavior.

### Verification
- Executed in disposable Windows Sandbox with `AIVEN_POSTGRES_URI=sqlite+pysqlite:///:memory:` set for test collection:
  `python -m pytest -q tests/test_authorization_repository.py`
  Result: **7 passed in 4.14s**.
- Tried collecting the new authorization suite together with `tests/rag/retrieval/test_adaptive_k_selector.py`. Collection was blocked when importing the existing embedding/Qdrant stack because Windows Sandbox lacks the PyTorch `c10.dll` dependency / Microsoft Visual C++ Redistributable. This is an environment blocker, not an authorization test failure.
- All sandbox test commands operate on a disposable copy; the source edits described above were made through MyPC workspace file operations.

### Migration / deployment note
- The migration SQL has been created but has **not** been applied to the configured PostgreSQL database. Apply `migrations/20261103_multi_department_authorization.sql` before deploying/running the updated authorization repository against an existing database, otherwise the new association table will be missing.
- Fresh databases created from current model metadata will include the new association table.

### Remaining work / freeze status
- Authorization implementation and its focused SQLite regression tests are complete for this pass, but PostgreSQL migration execution/integration verification is still outstanding.
- Ingestion/retrieval are **not frozen**.
- Next pass: non-empty summary validation at registration; verify the downloaded PDF SHA-256 against `DocumentVersion.file_hash` before extraction; set AdaptiveKSelector default `k_min=3`; correct empty-response stop reason; then inspect OCR fallback/config, exact-hash matching short-circuit, page-number helper, validation edge cases and lifecycle reconciliation. Run tests in bounded batches and record environmental blockers accurately.


## Checkpoint — clean database rebuild workflow (2026-11-03)

The user confirmed the development database is empty and requested no migration-based setup. Use a clean table rebuild from SQLAlchemy metadata instead.

### Model changes
- Removed the legacy single `department_id` column and department relationship from `OrganizationMembership`.
- `OrganizationDepartmentMembership` is now the sole membership-to-department association and supports multiple departments per member.
- Added ORM relationships:
  - `OrganizationMembership.department_assignments`
  - `OrganizationDepartment.member_assignments`
  - association row links back to both parents.
- Updated authorization repository to derive all department grants solely from `organization_department_memberships`. No stale `OrganizationMembership.department_id` or `membership.department_id` references remained in a source scan.
- Fixed SQLAlchemy overlapping relationship declarations with `overlaps` so targeted tests run without mapper warnings.
- The active model registry includes the association model. `DepartmentAccessPolicy` remains excluded from active model registration.

### Database creation workflow
- Added `scripts/database.py`. It imports all mapped models, displays the configured DB name and registered table count, and requires exact typed confirmation `RESET <database-name>` before destructive action.
- On confirmation, it uses `Base.metadata.drop_all()` followed by `Base.metadata.create_all()` in one engine transaction.
- Important: this drops/recreates all SQLAlchemy-managed tables; it does NOT drop the PostgreSQL database object itself or unregistered DB objects. This is intentional and appropriate when the database exists but the project schema is to be reset.
- Updated `scripts/create_tables.py` to delegate to the new reset function for compatibility, so there is one reset implementation.
- The former SQL migration file `migrations/20261103_multi_department_authorization.sql` has been replaced with comments only; it has no executable migration SQL. MyPC workspace tools exposed no file-delete operation, so the obsolete file remains as a harmless placeholder. Do not apply it.
- Do not run the reset script against the user's real DB in this chat. The user will run it after reviewing the script.

### Verification in disposable Windows Sandbox
- `tests/test_authorization_repository.py`: **7 passed in 4.10s**, zero warnings.
- Exercised `scripts/database.py` with `AIVEN_POSTGRES_URI=sqlite+pysqlite:///:memory:` and a mocked exact confirmation. It dropped/recreated all 10 registered tables successfully in the isolated sandbox.
- `python -m py_compile` over all changed models, repository, test and both scripts: succeeded.
- Source scan confirmed no stale single-department membership references.
- No connection to, or changes in, the real PostgreSQL database were made.

### Next bounded work
Proceed with the next ingestion/retrieval fixes only after this checkpoint:
1. Validate non-empty summary in registration data before creating a pending version.
2. Verify downloaded PDF SHA-256 against registered `DocumentVersion.file_hash` before extraction/indexing.
3. Change AdaptiveKSelector default `k_min` from 5 to 3.
4. Fix the empty retrieval response stop reason to reflect the actual empty reason.
5. Then inspect OCR quality fallback/config wiring, exact-hash matching short-circuit, page-number helper, validation edge cases and lifecycle reconciliation.
Ingestion/retrieval remain not frozen. The reset script is a manual destructive operation; do not execute it against the real DB without the user's action.


## Checkpoint — ingestion integrity and retrieval defaults (2026-11-03)

### User database status
- User reported completing the local reset prompt for configured PostgreSQL database `testing`.
- This is user-reported; no live PostgreSQL connection was made by ChatGPT to independently verify the table state.
- Do not run `scripts/database.py` again unless the user explicitly requests another reset.

### Source changes in this pass
1. `app/services/document_registration/registration_service.py`
   - Registration now rejects blank/non-string summaries before opening the savepoint or creating records.
   - Registration now requires a file hash consisting of exactly 64 hexadecimal characters (SHA-256 representation). This ensures the indexing stage has an integrity reference.
2. `app/services/document_indexing/indexing_orchestrator.py`
   - Imports `PDFHashService`.
   - `_load_version()` rejects missing/malformed registered SHA-256 before downloading.
   - After download and non-empty file check, computes SHA-256 of the downloaded PDF and compares case-insensitively against `DocumentVersion.file_hash`.
   - Mismatch aborts before PDF extraction/indexing; existing cleanup and PostgreSQL rollback path handles the failure.
3. `app/rag/retrieval/adaptive_k_selector.py`
   - Default `k_min` changed from 5 to 3.
4. `app/services/retrieval/retrieval_service.py`
   - `_empty_response()` now sets `expansion.stop_reason` to the actual reason argument, rather than always reporting `no_authorized_document_versions`.
5. Regression tests:
   - Added blank-summary and missing-hash validation tests to `tests/services/test_document_registration.py`.
   - Added valid fixture SHA-256 and mismatch-before-extraction test to `tests/services/test_document_indexing_orchestrator.py`.
   - Added default-k test to `tests/rag/retrieval/test_adaptive_k_selector.py`.
   - Added empty-response reason assertion to `tests/services/test_retrieval_service.py`.

### Verification in disposable MyPC Windows Sandbox
- `tests/test_authorization_repository.py`: **7 passed**.
- Registration validation selection: **2 passed, 8 deselected**.
- `tests/services/test_document_indexing_orchestrator.py`: **15 passed** using stubbed PDF loader and Qdrant summary module because native PyMuPDF dependencies fail to load in sandbox.
- `tests/rag/retrieval/test_adaptive_k_selector.py`: **20 passed** with the package pipeline stubbed to avoid importing the heavyweight Qdrant/embedding stack.
- `tests/services/test_retrieval_service.py`: **6 passed** with the external pipeline, summary-store, and sentence-transformers symbols stubbed to avoid unavailable model/native dependencies.
- `tests/test_hash_service.py`: **5 passed**.
- `python -m py_compile` across changed service modules and tests: succeeded.
- Direct module execution also confirmed `AdaptiveKSelector().k_min == 3`.
- A first un-stubbed test collection for indexing was blocked by missing native PyMuPDF `_extra` DLL in sandbox. An earlier combined adaptive test collection similarly hit PyTorch `c10.dll`. This is a sandbox runtime limitation; stubbed test suites passed.
- No code was executed against the user's production/external stores. Sandbox is disposable.

### Ingestion/retrieval status
- The audit's high-priority integrity/default/response fixes above are implemented and targeted tests pass.
- Do **not** declare ingestion and retrieval fully frozen yet.
- Remaining audit items:
  1. OCR fallback quality-aware behavior (preserve better native text when OCR output is empty/inferior).
  2. Wire OCR threshold/engine/settings rather than hardcoded values.
  3. Exact file/content hash matches should short-circuit semantic summary search.
  4. Review/fix dormant page sampler helper's page-number assumptions; page numbering is one-based end-to-end.
  5. Duplicate detection concurrency and Qdrant lifecycle reconciliation need further review.
  6. Continue reviewing numeric/bool input validation and any remaining ACL direct tests / PostgreSQL integration.
- Next step: inspect OCR loader/config and matching orchestrator, then make a separate bounded pass. Keep task scope finite and append this memory at the next checkpoint.


## Checkpoint — OCR policy, page numbering, and exact-hash short circuit (2026-11-03)

### Changes made
1. `app/rag/pdf_reader/loader.py`
   - Loader defaults now come from settings rather than hardcoded threshold/engine:
     - `MIN_NATIVE_CHARS`
     - `OCR_ENGINE` (fallback EasyOCR)
     - `OCR_LANGS`
     - `RENDER_DPI`
     - `OCR_ALL_PAGES`
     - `OCR_MERGE_WITH_NATIVE`
   - EasyOCR, Tesseract, and FastOCR page-level dispatch uses configured language/DPI options.
   - OCR output no longer unconditionally replaces native extraction.
   - Empty OCR and shorter OCR preserve native text.
   - OCR longer than native is preferred only when mean confidence is absent or at least 0.5; when native text is empty, non-empty OCR is accepted as the only content source.
   - Optional merge mode combines distinct native/OCR text, with containment checks to avoid duplicating text that is already included.
   - Metadata now records `ocr_attempted`, `ocr_used`, `ocr_text_length`, and `ocr_mean_confidence`, plus actual extraction method.
2. `app/rag/pdf_reader/ocr.py`
   - OCR singleton is initialized with configured EasyOCR languages and render DPI.
   - EasyOCR initialization is deferred until the first EasyOCR call, avoiding unnecessary model loading when configured engine is Tesseract/FastOCR.
   - EasyOCR and Tesseract results expose mean word/detection confidence in page metadata.
   - FastOCR page dispatch now forwards configured `languages` to its internal call. Current `FastOCRLoader` constructor itself only accepts file path and API key, so actual language enforcement remains constrained by that integration's API.
3. `app/rag/ingestion/pdf_sampler.py`
   - `sample_with_page_numbers()` now follows the pipeline's one-based page metadata contract directly.
   - Missing page metadata falls back to the original one-based list position.
   - Invalid, bool, zero, or negative page metadata raises a clear `ValueError`.
4. `app/services/document_matching/matching_orchestrator.py`
   - Exact file-hash or exact normalized-content-hash matches now short-circuit before semantic summary search.
   - Exact matches retain priority (file hash before content hash), preserve both exact-match groups when both exist, and set semantic candidates to empty.
5. Tests:
   - Added `tests/test_pdf_loader_policy.py` for empty/shorter OCR, confidence-based preference, merge behavior, force OCR, page metadata, and settings wiring.
   - Updated `tests/test_pdf_sampler.py` fixtures/expectations to use one-based page metadata.
   - Updated `tests/services/test_document_matching_orchestrator.py` to verify exact matches skip summary matcher.

### Verification in disposable MyPC Windows Sandbox
- `tests/services/test_document_matching_orchestrator.py`: **11 passed**.
- `tests/test_pdf_sampler.py`: **10 passed**.
- `tests/test_pdf_loader_policy.py`: **7 passed**, with fake native/OCR clients injected because native PDF/OCR DLLs cannot be loaded in the sandbox.
- `python -m py_compile` for changed loader, OCR, sampler, matching service, and tests: succeeded.
- No actual PDF/OCR service, Qdrant instance, or external PostgreSQL was modified. Sandbox runs against a disposable workspace copy.

### Caveats
- OCR quality comparison uses extracted character count plus available mean confidence. The 0.5 confidence threshold is a heuristic, not a calibrated probability. It should be evaluated on representative scanned PDFs before production.
- FastOCR language selection is accepted/passed through the page API but the installed `FastOCRLoader` wrapper does not expose a languages constructor parameter, so confirm provider behavior before depending on multilingual enforcement.
- OCR_ALL_PAGES is intentionally an attempt policy; OCR content is still selected only when it contributes better/merged content.

### Remaining before ingestion/retrieval freeze
- Duplicate registration race: the current duplicate check can race between concurrent ingestion requests. Review a DB-backed reservation/unique-key strategy before claiming concurrency safety.
- Qdrant/PostgreSQL lifecycle reconciliation: sync-pending flags exist, but no durable reconciliation worker/outbox has been verified.
- Review numeric/bool validation edge cases in other services, and run a broader regression suite when native dependencies are available.
- Then perform a final cross-layer audit (auth, registration, indexing, retrieval, OCR, matching, page numbering) and only then freeze both layers.
- Evaluations phase follows the freeze.


## Checkpoint — duplicate concurrency guard, Qdrant lifecycle repair, and validation hardening (2026-11-03)

### Duplicate-registration concurrency
- Updated `app/services/document_ingestion/ingestion_service.py`.
- Added deterministic signed 64-bit lock keys derived from SHA-256 of (organization ID, hash type, hash value).
- On PostgreSQL, ingestion acquires `pg_advisory_xact_lock` for both available file/content hashes in sorted order **before duplicate lookup**. Locks remain held while the request checks for matches, uploads/registers, and commits. A competing same-hash transaction then rechecks after the first transaction commits.
- Keys include organization ID, so identical file/content hashes in separate tenants do not block each other. Sorted acquisition avoids inconsistent lock ordering.
- Non-PostgreSQL dialects skip this PostgreSQL-specific locking; production DB is PostgreSQL.
- Added 3 tests for deterministic/organization-scoped keys, sorted lock acquisition, and non-PostgreSQL skip.
- Limitation: locks coordinate application ingestion transactions that use this method. Direct DB writers that bypass the ingestion service are not protected by the advisory-lock convention. No live PostgreSQL multi-session concurrency test was possible in the isolated network-disabled sandbox.

### Repeatable Qdrant lifecycle reconciliation
- Added `app/services/document_indexing/lifecycle_reconciler.py`.
- It reads PostgreSQL active/superseded version state and reapplies that status to chunk payloads and summary points. PostgreSQL remains authoritative; no second lifecycle state table/outbox is introduced.
- Per-version failures are isolated and reported, so one failure does not stop the rest of the run.
- Added `scripts/reconcile_indexes.py`:
  - `python scripts/reconcile_indexes.py` performs a read-only dry-run by default.
  - `python scripts/reconcile_indexes.py --apply` applies lifecycle projections to Qdrant.
  - Dry-run does not initialize/connect to Qdrant.
  - Apply mode is replayable/idempotent and re-upserts each summary point plus updates the chunk lifecycle status.
- Added `tests/services/test_lifecycle_reconciler.py` covering dry-run, active/superseded projection, failure isolation, and input validation.
- Limitation: this repairs lifecycle metadata/status for existing chunk points and recreates/upserts summary points. It does **not** re-create missing chunk vectors, re-extract PDFs, or serve as an automatic background worker. Run the command when lifecycle sync errors are reported or during an operations audit.
- CLI dry-run was executed successfully in sandbox using an empty in-memory SQLite schema: 0 versions planned, no Qdrant connection/write attempted.

### Additional OCR and schema hardening
- Refined `PDFLoader` merge behavior: with `OCR_MERGE_WITH_NATIVE=True`, distinct shorter OCR text is now merged when it is non-empty and not low-confidence, rather than requiring OCR to be longer than native text. Added a corresponding test.
- Added `sqlite_where=status='active'` beside the existing PostgreSQL partial-index predicate for `idx_one_active_version`. SQLite test schemas now correctly allow multiple pending/superseded versions while enforcing a single active one, matching PostgreSQL intent.
- Removed a stale `department="HR"` constructor argument from `tests/services/test_document_registration.py`; department assignment is not part of `DocumentRegistrationData`.

### Numeric / boolean validation hardening
- `RetrievalOrchestrator.retrieval_concurrency` now requires a positive integer (not bool/fractional).
- `CrossEncoderReranker` now requires positive integer `batch_size`, `max_length`, and optional `top_k`.
- `CandidateDocumentGenerator.similarity_threshold` now rejects booleans, non-numeric values, NaN/infinity, and values outside [0, 1].
- `DocumentSummaryMatcher.threshold` now rejects booleans, non-numeric values, NaN/infinity, and values outside [0, 1].
- Added regression tests for the above.

### Verification in disposable MyPC Windows Sandbox
The following targeted suites passed:
- `tests/services/test_document_ingestion.py`: **15 passed** (native PDF validator/loader and Qdrant summary import boundaries stubbed because the sandbox cannot load PyMuPDF native DLLs).
- `tests/services/test_lifecycle_reconciler.py`: **4 passed**.
- `tests/services/test_document_matching_orchestrator.py`: **11 passed**.
- `tests/test_pdf_sampler.py`: **10 passed**.
- `tests/test_authorization_repository.py`: **7 passed**.
- `tests/test_pdf_loader_policy.py`: **8 passed** (fake native/OCR clients).
- `tests/services/test_document_registration.py`: **10 passed** using in-memory SQLite with all models created.
- `tests/test_document_version_lifecycle.py`: **15 passed** using in-memory SQLite with all models created.
- `tests/rag/retrieval/test_cross_encoder_reranker.py`: **15 passed** (pipeline and sentence-transformers import boundaries stubbed due missing PyTorch DLL).
- `tests/rag/retrieval/test_candidate_document_generator.py`: **11 passed** (pipeline and summary-store imports stubbed).
- `tests/services/test_document_summary_matcher.py`: **18 passed**.
- `tests/services/test_retrieval_service.py`: **7 passed** (pipeline, summary store and sentence-transformers import boundaries stubbed).
- `python -m py_compile` across changed service/model/retrieval/script/test files: succeeded.
- Total in this verification batch: **131 passed** across the listed targeted suites.
- One initial, un-stubbed cross-encoder test collection failed because the sandbox lacks the PyTorch `c10.dll` / Microsoft Visual C++ runtime. The same suite passed (15 tests) after stubbing the heavyweight import boundary. No live stores were contacted.

### Freeze status / next bounded pass
- Major application-level ingestion/retrieval findings have fixes and targeted test coverage.
- Do **not** declare production freeze yet. Remaining verification requires environments unavailable inside the disposable sandbox:
  1. Run a real two-session PostgreSQL concurrency test against the configured Postgres DB (without resetting it) to prove same-hash advisory lock serialization.
  2. Run `scripts/reconcile_indexes.py` in dry-run and, after review, `--apply` against the configured Qdrant deployment; inspect outcome counts/errors.
  3. Exercise OCR on representative PDFs in a runtime with PyMuPDF/EasyOCR/Tesseract native dependencies installed, and calibrate the 0.5 confidence heuristic on actual scans.
  4. Run the complete project test suite in the developer environment (native dependencies available), not only the targeted sandbox tests.
  5. Do a short final source audit for remaining bool/fractional validation and verify the app's runtime/composition roots instantiate the intended defaults.
- No live PostgreSQL reset, no live Qdrant write, and no external storage operation was performed during this pass.
- Once these integration checks are complete, freeze ingestion/retrieval and move to evaluations.
