-- Unknown legacy freshness remains NULL until the provider is observed again.
ALTER TABLE market_bars ADD COLUMN last_observed_at TEXT;
CREATE TABLE signal_evaluations (
    signal_id TEXT PRIMARY KEY REFERENCES signals(id),
    state TEXT NOT NULL,
    reason TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    entry_session TEXT,
    exit_session TEXT,
    evaluation_version TEXT NOT NULL
) STRICT;
