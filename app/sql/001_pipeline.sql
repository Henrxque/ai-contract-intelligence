-- Raw documents, extraction staging, normalized output and operational lineage.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY CHECK(length(document_id) = 64),
    original_filename TEXT NOT NULL,
    content BLOB NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    pipeline_version TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('local','openai')),
    provider_model TEXT,
    sample INTEGER NOT NULL CHECK(sample IN (0,1)),
    state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_token TEXT,
    lease_expires REAL,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_id, config_hash)
);
CREATE TABLE IF NOT EXISTS attempts (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    attempt_number INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('running','succeeded','failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_code TEXT,
    error_message TEXT,
    PRIMARY KEY(run_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS extraction_staging (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    pages_json TEXT NOT NULL CHECK(json_valid(pages_json)),
    extraction_json TEXT CHECK(extraction_json IS NULL OR json_valid(extraction_json)),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    quality_status TEXT NOT NULL CHECK(quality_status IN ('checks_passed','needs_review')),
    elapsed_ms INTEGER NOT NULL,
    completed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contract_fields (
    run_id TEXT NOT NULL REFERENCES analyses(run_id),
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    field_group TEXT NOT NULL,
    value TEXT,
    status TEXT NOT NULL CHECK(status IN ('supported','missing','uncertain','invalid')),
    required INTEGER NOT NULL CHECK(required IN (0,1)),
    PRIMARY KEY(run_id, field_key)
);
CREATE TABLE IF NOT EXISTS field_evidence (
    run_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    page_number INTEGER NOT NULL CHECK(page_number > 0),
    quote TEXT NOT NULL,
    PRIMARY KEY(run_id, field_key, ordinal),
    FOREIGN KEY(run_id, field_key) REFERENCES contract_fields(run_id, field_key)
);
CREATE TABLE IF NOT EXISTS review_findings (
    run_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('error','warning','info')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    PRIMARY KEY(run_id, ordinal),
    FOREIGN KEY(run_id, field_key) REFERENCES contract_fields(run_id, field_key)
);
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    sample INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_items (
    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    ordinal INTEGER NOT NULL,
    input_filename TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    disposition TEXT NOT NULL DEFAULT 'queued',
    observed_state TEXT NOT NULL DEFAULT 'queued',
    PRIMARY KEY(batch_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state, updated_at);
CREATE INDEX IF NOT EXISTS idx_fields_status ON contract_fields(status);
CREATE VIEW IF NOT EXISTS accepted_contract_fields AS
    SELECT f.* FROM contract_fields f
    JOIN analyses a USING(run_id)
    WHERE a.quality_status = 'checks_passed' AND f.status = 'supported';
CREATE VIEW IF NOT EXISTS quality_quarantine AS
    SELECT f.*, a.quality_status FROM contract_fields f
    JOIN analyses a USING(run_id)
    WHERE a.quality_status = 'needs_review';
