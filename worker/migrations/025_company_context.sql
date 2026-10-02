-- Bounded display projections only; no trading or historical research authority.
CREATE TABLE company_context (
    symbol TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('queued','running','ready','unavailable')),
    requested_at TEXT NOT NULL,
    updated_at TEXT,
    retry_after TEXT,
    payload_json TEXT CHECK(payload_json IS NULL OR (json_valid(payload_json) AND length(payload_json)<=131072)),
    error TEXT
) STRICT;
CREATE INDEX company_context_queue ON company_context(status, requested_at);
CREATE TABLE company_context_directory (
    source TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
) STRICT;
