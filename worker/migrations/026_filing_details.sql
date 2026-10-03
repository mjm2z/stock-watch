CREATE TABLE filing_details (
 symbol TEXT NOT NULL, accession TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','ready','unavailable')),
 requested_at TEXT NOT NULL, updated_at TEXT, retry_after TEXT,
 payload_json TEXT CHECK(payload_json IS NULL OR (json_valid(payload_json) AND length(CAST(payload_json AS BLOB))<=524288)),
 error TEXT, PRIMARY KEY(symbol,accession)
) STRICT;
CREATE INDEX filing_details_queue ON filing_details(status,requested_at);
