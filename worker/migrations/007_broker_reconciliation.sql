CREATE TABLE broker_account_snapshots (
    id INTEGER PRIMARY KEY,
    captured_at TEXT NOT NULL UNIQUE,
    broker TEXT NOT NULL CHECK (broker = 'alpaca-paper'),
    account_id TEXT NOT NULL,
    status TEXT NOT NULL,
    currency TEXT NOT NULL,
    cash REAL NOT NULL,
    equity REAL NOT NULL,
    long_market_value REAL NOT NULL,
    trading_blocked INTEGER NOT NULL CHECK (trading_blocked IN (0, 1)),
    account_blocked INTEGER NOT NULL CHECK (account_blocked IN (0, 1)),
    trade_suspended INTEGER NOT NULL CHECK (trade_suspended IN (0, 1)),
    raw_json TEXT NOT NULL CHECK (json_valid(raw_json))
) STRICT;

CREATE TABLE broker_position_snapshots (
    account_snapshot_id INTEGER NOT NULL
        REFERENCES broker_account_snapshots(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    quantity REAL NOT NULL CHECK (quantity > 0),
    market_value REAL NOT NULL,
    current_price REAL NOT NULL,
    cost_basis REAL NOT NULL,
    side TEXT NOT NULL CHECK (side = 'long'),
    raw_json TEXT NOT NULL CHECK (json_valid(raw_json)),
    PRIMARY KEY (account_snapshot_id, symbol)
) STRICT;

CREATE TABLE broker_account_activities (
    broker TEXT NOT NULL CHECK (broker = 'alpaca-paper'),
    activity_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    symbol TEXT,
    net_amount REAL,
    quantity REAL,
    per_share_amount REAL,
    captured_at TEXT NOT NULL,
    raw_json TEXT NOT NULL CHECK (json_valid(raw_json)),
    PRIMARY KEY (broker, activity_id)
) STRICT;

CREATE INDEX broker_account_activities_symbol_time
    ON broker_account_activities(symbol, occurred_at DESC);

CREATE TABLE broker_reconciliations (
    id INTEGER PRIMARY KEY,
    captured_at TEXT NOT NULL UNIQUE,
    account_snapshot_id INTEGER NOT NULL UNIQUE
        REFERENCES broker_account_snapshots(id),
    status TEXT NOT NULL CHECK (status IN ('matched', 'drift', 'blocked')),
    expected_positions_json TEXT NOT NULL CHECK (json_valid(expected_positions_json)),
    actual_positions_json TEXT NOT NULL CHECK (json_valid(actual_positions_json)),
    discrepancies_json TEXT NOT NULL CHECK (json_valid(discrepancies_json)),
    corporate_actions_json TEXT NOT NULL CHECK (json_valid(corporate_actions_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE INDEX broker_reconciliations_status_time
    ON broker_reconciliations(status, captured_at DESC);
