-- Execution policy is versioned separately from the unchanged ranking strategy.
CREATE TABLE paper_exit_timing_policies (
    strategy_version_id TEXT PRIMARY KEY REFERENCES strategy_versions(id),
    policy_version TEXT NOT NULL CHECK (policy_version='near-close-v1'),
    minutes_before_close INTEGER NOT NULL CHECK (minutes_before_close=5),
    activated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;
ALTER TABLE paper_trade_lots ADD COLUMN target_session_close_at TEXT;
ALTER TABLE paper_trade_lots ADD COLUMN exit_timing_policy TEXT;
