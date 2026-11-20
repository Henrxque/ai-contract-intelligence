-- Document identity, run configuration and execution/quality outcomes.
SELECT r.run_id, d.original_filename, r.document_id, r.pipeline_version,
       r.mode, r.provider_model, r.state, r.attempt_count, a.quality_status
FROM runs r
JOIN documents d USING(document_id)
LEFT JOIN analyses a USING(run_id)
ORDER BY r.created_at;

SELECT run_id, field_key, value, status
FROM accepted_contract_fields
ORDER BY run_id, field_key;

SELECT run_id, field_key, value, status
FROM quality_quarantine
WHERE status != 'supported'
ORDER BY run_id, field_key;

SELECT d.original_filename, f.field_key, f.value, f.status, e.page_number, e.quote
FROM contract_fields f
JOIN runs r USING(run_id)
JOIN documents d USING(document_id)
LEFT JOIN field_evidence e USING(run_id, field_key)
ORDER BY r.run_id, f.field_key, e.ordinal;

SELECT run_id, attempt_number, state, started_at, finished_at, error_code
FROM attempts
ORDER BY started_at;

-- Should return no rows.
PRAGMA foreign_key_check;
