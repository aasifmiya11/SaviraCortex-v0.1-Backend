-- RAG evaluation dataset and human relevance labels.
CREATE TABLE IF NOT EXISTS generation_feedback (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    generated_queries JSON NOT NULL DEFAULT '[]'::json,
    generated_query_count INTEGER NOT NULL DEFAULT 0,
    retrieval_trace JSON NOT NULL DEFAULT '{}'::json,
    retrieved_documents JSON NOT NULL DEFAULT '[]'::json,
    answer_markdown TEXT NOT NULL,
    answer_status VARCHAR(40) NOT NULL,
    feedback_status VARCHAR(20),
    feedback_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_generation_feedback_status
        CHECK (feedback_status IS NULL OR feedback_status IN ('relevant', 'not_relevant'))
);

CREATE INDEX IF NOT EXISTS idx_generation_feedback_org_created
    ON generation_feedback (organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_generation_feedback_org_label
    ON generation_feedback (organization_id, feedback_status);
