-- Persist role and department selections on pending invitations.
ALTER TABLE organization_invitations
    ADD COLUMN IF NOT EXISTS assigned_role_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS assigned_department_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
