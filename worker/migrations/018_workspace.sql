-- Presentation metadata and jobs are additive; immutable legacy versions stay intact.
CREATE TABLE workspace_drafts (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, asset TEXT NOT NULL CHECK(asset IN ('stocks','bitcoin')),
 document_json TEXT NOT NULL, updated_at TEXT NOT NULL, published_version TEXT REFERENCES system_versions(id),
 archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE workspace_jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', progress INTEGER NOT NULL DEFAULT 0,
 result_json TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE INDEX workspace_jobs_pending ON workspace_jobs(status,created_at);
CREATE TABLE crypto_chart_cache (
 key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
ALTER TABLE btc_allocations ADD COLUMN started_at TEXT;
ALTER TABLE btc_allocations ADD COLUMN entry_price TEXT;
-- Existing orders retain their authority; advance funding alone is not activation.
UPDATE btc_allocations SET started_at=(SELECT MIN(created_at) FROM btc_orders WHERE btc_orders.version_id=btc_allocations.version_id)
 WHERE EXISTS(SELECT 1 FROM btc_orders WHERE btc_orders.version_id=btc_allocations.version_id);
CREATE TABLE workspace_version_details (
 version_id TEXT PRIMARY KEY REFERENCES system_versions(id),
 draft_id TEXT REFERENCES workspace_drafts(id),
 parent_version TEXT REFERENCES system_versions(id),
 archived INTEGER NOT NULL DEFAULT 0
);
