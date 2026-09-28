-- Additive controls; preserve every existing strategy, allocation and order.
CREATE TABLE system_entry_controls (
 version_id TEXT PRIMARY KEY REFERENCES system_versions(id),
 paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)),
 exit_requested INTEGER NOT NULL DEFAULT 0 CHECK(exit_requested IN (0,1)),
 decision_floor TEXT,
 updated_at TEXT NOT NULL,
 attribution_json TEXT NOT NULL
);
