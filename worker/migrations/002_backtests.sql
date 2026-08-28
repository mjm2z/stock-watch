CREATE TABLE backtest_runs (
    id TEXT PRIMARY KEY,
    strategy_version_id TEXT NOT NULL REFERENCES strategy_versions(id),
    universe_snapshot_id INTEGER NOT NULL REFERENCES universe_snapshots(id),
    dataset_version TEXT NOT NULL,
    dataset_sha256 TEXT NOT NULL,
    feature_set_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    survivorship_biased INTEGER NOT NULL CHECK (survivorship_biased IN (0, 1)),
    round_trip_cost_bps REAL NOT NULL CHECK (round_trip_cost_bps >= 0),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(config_json)),
    metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metrics_json)),
    started_at TEXT,
    completed_at TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(strategy_version_id, universe_snapshot_id, dataset_sha256, feature_set_version, config_json)
) STRICT;

CREATE INDEX backtest_runs_recent
    ON backtest_runs(created_at DESC, status);

CREATE TABLE backtest_splits (
    id INTEGER PRIMARY KEY,
    backtest_run_id TEXT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    split_index INTEGER NOT NULL CHECK (split_index >= 0),
    train_start TEXT NOT NULL,
    train_end TEXT NOT NULL,
    validation_start TEXT NOT NULL,
    validation_end TEXT NOT NULL,
    test_start TEXT NOT NULL,
    test_end TEXT NOT NULL,
    selected_threshold REAL CHECK (selected_threshold BETWEEN 0 AND 100),
    validation_metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(validation_metrics_json)),
    test_metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(test_metrics_json)),
    UNIQUE(backtest_run_id, split_index),
    UNIQUE(id, backtest_run_id),
    CHECK (train_start <= train_end),
    CHECK (train_end < validation_start),
    CHECK (validation_start <= validation_end),
    CHECK (validation_end < test_start),
    CHECK (test_start <= test_end)
) STRICT;

CREATE TABLE backtest_trades (
    id INTEGER PRIMARY KEY,
    backtest_run_id TEXT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    backtest_split_id INTEGER,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    signal_session TEXT NOT NULL,
    horizon_trading_days INTEGER NOT NULL CHECK (horizon_trading_days IN (5, 21, 63, 105)),
    opportunity_score REAL NOT NULL CHECK (opportunity_score BETWEEN 0 AND 100),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    notional_usd REAL NOT NULL CHECK (notional_usd > 0),
    entry_session TEXT NOT NULL,
    exit_session TEXT NOT NULL,
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    exit_price REAL NOT NULL CHECK (exit_price > 0),
    quantity REAL NOT NULL CHECK (quantity > 0),
    gross_return REAL NOT NULL,
    modeled_cost_return REAL NOT NULL CHECK (modeled_cost_return >= 0),
    net_return REAL NOT NULL,
    spy_return REAL NOT NULL,
    excess_return REAL NOT NULL,
    beat_spy INTEGER NOT NULL CHECK (beat_spy IN (0, 1)),
    terminal_positive INTEGER NOT NULL CHECK (terminal_positive IN (0, 1)),
    terminal_at_least_5 INTEGER NOT NULL CHECK (terminal_at_least_5 IN (0, 1)),
    terminal_at_least_10 INTEGER NOT NULL CHECK (terminal_at_least_10 IN (0, 1)),
    touched_5 INTEGER NOT NULL CHECK (touched_5 IN (0, 1)),
    touched_10 INTEGER NOT NULL CHECK (touched_10 IN (0, 1)),
    maximum_favorable_excursion REAL NOT NULL,
    maximum_adverse_excursion REAL NOT NULL,
    pnl_usd REAL NOT NULL,
    FOREIGN KEY(backtest_split_id, backtest_run_id)
        REFERENCES backtest_splits(id, backtest_run_id) ON DELETE CASCADE,
    CHECK (signal_session < entry_session),
    CHECK (entry_session <= exit_session),
    UNIQUE(backtest_run_id, instrument_id, signal_session, horizon_trading_days)
) STRICT;

CREATE INDEX backtest_trades_analysis
    ON backtest_trades(backtest_run_id, horizon_trading_days, opportunity_score);

CREATE TABLE backtest_rejections (
    id INTEGER PRIMARY KEY,
    backtest_run_id TEXT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    backtest_split_id INTEGER,
    instrument_id INTEGER REFERENCES instruments(id),
    symbol TEXT NOT NULL,
    signal_session TEXT NOT NULL,
    horizon_trading_days INTEGER NOT NULL CHECK (horizon_trading_days IN (5, 21, 63, 105)),
    opportunity_score REAL NOT NULL CHECK (opportunity_score BETWEEN 0 AND 100),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    reason TEXT NOT NULL,
    FOREIGN KEY(backtest_split_id, backtest_run_id)
        REFERENCES backtest_splits(id, backtest_run_id) ON DELETE CASCADE,
    UNIQUE(backtest_run_id, symbol, signal_session, horizon_trading_days)
) STRICT;

CREATE INDEX backtest_rejections_reason
    ON backtest_rejections(backtest_run_id, reason);
