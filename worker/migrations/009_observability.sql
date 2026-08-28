CREATE TABLE operation_runs (
    id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    heartbeat_at TEXT NOT NULL,
    progress_current INTEGER,
    progress_total INTEGER,
    message TEXT,
    context_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(context_json)),
    result_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(result_json)),
    error_type TEXT,
    error_message TEXT,
    exception_chain_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(exception_chain_json)),
    traceback TEXT,
    host TEXT NOT NULL,
    process_id INTEGER NOT NULL
) STRICT;

CREATE INDEX operation_runs_recent
    ON operation_runs(started_at DESC);
CREATE INDEX operation_runs_status
    ON operation_runs(status, started_at DESC);

CREATE TABLE operation_events (
    id INTEGER PRIMARY KEY,
    operation_run_id TEXT NOT NULL REFERENCES operation_runs(id) ON DELETE CASCADE,
    occurred_at TEXT NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('debug', 'info', 'warning', 'error')),
    event TEXT NOT NULL,
    message TEXT NOT NULL,
    progress_current INTEGER,
    progress_total INTEGER,
    context_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(context_json))
) STRICT;

CREATE INDEX operation_events_run
    ON operation_events(operation_run_id, occurred_at, id);
