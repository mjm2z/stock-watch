-- Separate account coordinator: v1 deployments and stock ownership stay intact.
CREATE TABLE btc_accounts (
 id TEXT PRIMARY KEY, initial_cash TEXT NOT NULL DEFAULT '300', cash TEXT NOT NULL DEFAULT '300',
 high_water TEXT NOT NULL DEFAULT '300', risk_paused INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, checked_at TEXT, status TEXT NOT NULL DEFAULT 'ready'
);
CREATE TABLE btc_allocations (
 version_id TEXT PRIMARY KEY REFERENCES system_versions(id), account_id TEXT REFERENCES btc_accounts(id),
 budget TEXT NOT NULL, cash TEXT NOT NULL, quantity TEXT NOT NULL DEFAULT '0',
 high_water TEXT NOT NULL, entry_at TEXT, exit_due_at TEXT,
 risk_paused INTEGER NOT NULL DEFAULT 0, last_decision_at TEXT,
 approved_at TEXT NOT NULL, last_forward_at TEXT, state_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE btc_evaluations (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES system_versions(id),
 cutoff TEXT NOT NULL, due_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', progress INTEGER NOT NULL DEFAULT 0,
 result_json TEXT, error TEXT, created_at TEXT NOT NULL, finished_at TEXT,
 budget TEXT NOT NULL DEFAULT '60',
 UNIQUE(version_id,due_at)
);
CREATE TABLE btc_scenarios (
 id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL REFERENCES btc_evaluations(id),
 window_index INTEGER NOT NULL, profile TEXT NOT NULL, starts_at TEXT NOT NULL,
 ends_at TEXT NOT NULL, cache_key TEXT, status TEXT NOT NULL DEFAULT 'queued',
 reused INTEGER NOT NULL DEFAULT 0, result_json TEXT, error TEXT,
 UNIQUE(evaluation_id,window_index,profile)
);
CREATE TABLE btc_scenario_cache (
 key TEXT PRIMARY KEY, result_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE btc_qualifications (
 version_id TEXT PRIMARY KEY REFERENCES system_versions(id), evaluation_id TEXT REFERENCES btc_evaluations(id),
 status TEXT NOT NULL DEFAULT 'collecting', reason TEXT NOT NULL,
 pass_streak INTEGER NOT NULL DEFAULT 0, failed_once INTEGER NOT NULL DEFAULT 0,
 checked_at TEXT NOT NULL, next_review_at TEXT NOT NULL
);
CREATE TABLE btc_orders (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES system_versions(id),
 account_id TEXT NOT NULL REFERENCES btc_accounts(id), side TEXT NOT NULL,
 quantity TEXT NOT NULL, reserved_cash TEXT NOT NULL DEFAULT '0',
 filled_qty TEXT NOT NULL DEFAULT '0', filled_notional TEXT NOT NULL DEFAULT '0',
 broker_id TEXT, status TEXT NOT NULL DEFAULT 'pending', reference_price TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, response_json TEXT,
 evaluation_id TEXT, reason TEXT NOT NULL
);
CREATE TABLE btc_fees (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES btc_accounts(id),
 order_id TEXT REFERENCES btc_orders(id), payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'unattributed', captured_at TEXT NOT NULL
);
CREATE TABLE btc_forward (
 version_id TEXT NOT NULL REFERENCES system_versions(id), at TEXT NOT NULL,
 equity REAL NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(version_id,at)
);
CREATE TABLE btc_control_commands (
 id TEXT PRIMARY KEY, action TEXT NOT NULL, payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL, error TEXT
);
CREATE INDEX btc_orders_active ON btc_orders(account_id,status);
CREATE INDEX btc_evaluations_due ON btc_evaluations(status,due_at);
CREATE TABLE btc_enrollments (
 version_id TEXT PRIMARY KEY REFERENCES system_versions(id), enrolled_at TEXT NOT NULL,
 approved_at TEXT, paused INTEGER NOT NULL DEFAULT 0, state_json TEXT NOT NULL DEFAULT '{}',
 active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE btc_health (key TEXT PRIMARY KEY, at TEXT NOT NULL, error TEXT);
CREATE TABLE btc_fills (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES btc_orders(id),
 at TEXT NOT NULL, quantity TEXT NOT NULL, notional TEXT NOT NULL
);
CREATE TABLE btc_fee_allocations (
 fee_id TEXT NOT NULL REFERENCES btc_fees(id), order_id TEXT NOT NULL REFERENCES btc_orders(id),
 cash_fee TEXT NOT NULL, quantity_fee TEXT NOT NULL, method TEXT NOT NULL,
 PRIMARY KEY(fee_id,order_id)
);
ALTER TABLE btc_orders ADD COLUMN fee_cash_adjustment TEXT NOT NULL DEFAULT '0';
ALTER TABLE btc_orders ADD COLUMN fee_quantity_adjustment TEXT NOT NULL DEFAULT '0';
ALTER TABLE btc_accounts ADD COLUMN equity TEXT;
