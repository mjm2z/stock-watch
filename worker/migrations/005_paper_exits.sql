CREATE TABLE paper_exit_orders (
    id TEXT PRIMARY KEY,
    lot_id TEXT NOT NULL UNIQUE REFERENCES paper_trade_lots(id),
    client_order_id TEXT NOT NULL UNIQUE,
    broker_order_id TEXT UNIQUE,
    broker_request_id TEXT,
    quantity REAL NOT NULL CHECK (quantity > 0),
    order_type TEXT NOT NULL DEFAULT 'market' CHECK (order_type = 'market'),
    time_in_force TEXT NOT NULL DEFAULT 'day' CHECK (time_in_force = 'day'),
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'submitted', 'accepted', 'partially_filled',
        'filled', 'canceled', 'rejected', 'error'
    )),
    submitted_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(raw_json))
) STRICT;

CREATE INDEX paper_exit_orders_status
    ON paper_exit_orders(status, updated_at);

CREATE TABLE paper_exit_fills (
    id TEXT PRIMARY KEY,
    exit_order_id TEXT NOT NULL REFERENCES paper_exit_orders(id),
    broker_fill_id TEXT,
    filled_at TEXT NOT NULL,
    quantity REAL NOT NULL CHECK (quantity > 0),
    price REAL NOT NULL CHECK (price > 0),
    notional_usd REAL NOT NULL CHECK (notional_usd > 0),
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(raw_json)),
    UNIQUE(exit_order_id, broker_fill_id)
) STRICT;

ALTER TABLE signal_outcomes ADD COLUMN entry_session TEXT;
ALTER TABLE signal_outcomes ADD COLUMN exit_session TEXT;
