# 25. Operational Runbook

This runbook is an operational checklist derived from the implemented components. It does not assert that monitoring, alerting or deployment automation is already configured.

## Before processing documents

- Verify database, Redis, Qdrant, B2 and LLM service health.
- Confirm environment variables target the intended environment.
- Confirm the B2 bucket and Qdrant collection names.
- Confirm OCR binaries/language packs are available.
- Confirm sufficient storage and service quotas.
- Verify the caller's organization/user identity and access scope.

## Ingestion issue

1. Capture the ingestion outcome and stage.
2. Validate the source PDF and page count.
3. Check native extraction/OCR policy and usable text.
4. Compare file/content hashes for duplicates.
5. If upload succeeded but registration failed, verify object cleanup or remove the orphan through an approved procedure.
6. Do not auto-accept a potential match without review.

## Indexing issue

1. Identify the logical document and version.
2. Check version status in PostgreSQL.
3. Check whether the original object exists in B2.
4. Check chunk and summary records in Qdrant.
5. Inspect orchestrator/reconciler logs and tests for supported recovery.
6. Reconcile only after confirming the target version and expected lifecycle state.

## Retrieval issue

1. Confirm user membership and organization scope.
2. Confirm expected document IDs appear in the authorized catalogue.
3. Check cache freshness after permission changes.
4. Verify active/superseded/archive status.
5. Check candidate generation constraints.
6. Compare dense and lexical retrieval results.
7. Inspect fusion/reranking stages and model availability.

## Backups and restore

A production backup plan should cover PostgreSQL, B2 originals, Qdrant chunk collection, Qdrant summary collection and any required cache/configuration state. Redis authorization caches are generally rebuildable from authoritative records, but verify actual application dependencies before discarding them. Test restoration and cross-store reconciliation regularly.

## Known gaps at review time

- No implemented API route layer was found.
- No populated migration directory was found.
- Dedicated observability and task/worker packages were empty.
- No deployment manifests or production runbook were found in the reviewed root tree.
- Full test suite and production-like recovery were not executed during this documentation pass.
