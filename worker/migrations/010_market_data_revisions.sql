-- Current bars are a cache. Every accepted correction retains its before/after
-- image, and each successful scan freezes the actual bars it collected.
CREATE TABLE market_bar_revisions (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    timestamp TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    adjustment TEXT NOT NULL,
    provider TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ingestion_id INTEGER REFERENCES data_ingestions(id),
    previous_ingestion_id INTEGER REFERENCES data_ingestions(id),
    previous_json TEXT NOT NULL CHECK(json_valid(previous_json)),
    revised_json TEXT NOT NULL CHECK(json_valid(revised_json))
) STRICT;

CREATE TABLE scan_bar_snapshots (
    scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    bars_json TEXT NOT NULL CHECK(json_valid(bars_json)),
    PRIMARY KEY(scan_run_id, instrument_id)
) STRICT, WITHOUT ROWID;

-- Surface existing terminal collection failures without retrying old trades.
UPDATE scan_runs
SET status = 'failed',
    error = (SELECT error FROM job_runs
             WHERE json_extract(metadata_json, '$.scan_run_id') = scan_runs.id
               AND status = 'failed' ORDER BY completed_at DESC LIMIT 1),
    completed_at = (SELECT completed_at FROM job_runs
             WHERE json_extract(metadata_json, '$.scan_run_id') = scan_runs.id
               AND status = 'failed' ORDER BY completed_at DESC LIMIT 1)
WHERE status = 'queued' AND EXISTS (
    SELECT 1 FROM job_runs
    WHERE json_extract(metadata_json, '$.scan_run_id') = scan_runs.id
      AND status = 'failed'
);
