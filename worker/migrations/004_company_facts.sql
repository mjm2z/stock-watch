CREATE TABLE company_fact_documents (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    captured_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    facts_json TEXT NOT NULL CHECK (json_valid(facts_json)),
    provider TEXT NOT NULL DEFAULT 'sec',
    ingestion_id INTEGER REFERENCES data_ingestions(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instrument_id, captured_at, provider)
) STRICT;

CREATE INDEX company_fact_documents_point_in_time
    ON company_fact_documents(instrument_id, captured_at DESC);
