-- Independent validation evidence never participates in strategy qualification.
CREATE TABLE lean_comparisons (
 id TEXT PRIMARY KEY,
 version_id TEXT NOT NULL REFERENCES system_versions(id),
 dataset_id TEXT NOT NULL REFERENCES system_datasets(id),
 status TEXT NOT NULL CHECK(status IN ('queued','transferring','baseline','lean','comparing','complete','failed','canceled')),
 created_at TEXT NOT NULL, started_at TEXT, updated_at TEXT NOT NULL, finished_at TEXT,
 cancel_requested INTEGER NOT NULL DEFAULT 0,
 request_sha256 TEXT, baseline_path TEXT, result_path TEXT,
 summary_json TEXT CHECK(summary_json IS NULL OR (json_valid(summary_json) AND length(summary_json)<=524288)),
 error TEXT
) STRICT;
CREATE INDEX lean_comparisons_queue ON lean_comparisons(status,created_at);
CREATE TABLE lean_runner_health (id INTEGER PRIMARY KEY CHECK(id=1), updated_at TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json))) STRICT;
