ALTER TABLE job_runs ADD COLUMN available_at TEXT;
ALTER TABLE job_runs ADD COLUMN claimed_by TEXT;
ALTER TABLE job_runs ADD COLUMN heartbeat_at TEXT;

CREATE INDEX job_runs_available
    ON job_runs(status, available_at, scheduled_for);
