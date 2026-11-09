-- Add per-ingestion access configuration and persistent organization-wide document visibility.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS organization_wide_access BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE document_ingestion_sessions
    ADD COLUMN IF NOT EXISTS department_ids JSON NOT NULL DEFAULT '[]'::json,
    ADD COLUMN IF NOT EXISTS access_user_ids JSON NOT NULL DEFAULT '[]'::json,
    ADD COLUMN IF NOT EXISTS access_role_ids JSON NOT NULL DEFAULT '[]'::json,
    ADD COLUMN IF NOT EXISTS organization_wide_access BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_documents_org_wide_access
    ON documents (organization_id, organization_wide_access);
