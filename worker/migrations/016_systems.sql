-- Additive: legacy stock ledgers and dispatch remain unchanged.
CREATE TABLE system_versions (
 id TEXT PRIMARY KEY, asset TEXT NOT NULL CHECK(asset IN ('stocks','bitcoin')),
 template TEXT NOT NULL, config_json TEXT NOT NULL, config_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL, hypothesis TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER system_versions_immutable BEFORE UPDATE ON system_versions
 BEGIN SELECT RAISE(ABORT,'Create a new immutable system version'); END;
CREATE TABLE system_datasets (
 id TEXT PRIMARY KEY, asset TEXT NOT NULL, path TEXT NOT NULL,
 sha256 TEXT NOT NULL, manifest_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE system_runs (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES system_versions(id),
 dataset_id TEXT NOT NULL REFERENCES system_datasets(id),
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','canceled')),
 progress INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
 result_json TEXT, error TEXT
);
CREATE TABLE system_deployments (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES system_versions(id),
 mode TEXT NOT NULL CHECK(mode IN ('shadow','paper','paused')),
 account_id TEXT, started_at TEXT NOT NULL, high_water REAL NOT NULL DEFAULT 300,
 last_decision_at TEXT, state_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(version_id)
);
CREATE UNIQUE INDEX system_one_paper_account ON system_deployments(account_id) WHERE mode='paper';
CREATE TABLE system_observations (
 id INTEGER PRIMARY KEY, deployment_id TEXT NOT NULL REFERENCES system_deployments(id),
 observed_at TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
 UNIQUE(deployment_id,observed_at,kind)
);
CREATE TABLE system_orders (
 id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL REFERENCES system_deployments(id),
 symbol TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('buy','sell')),
 request_json TEXT NOT NULL, broker_id TEXT, status TEXT NOT NULL DEFAULT 'pending',
 filled_qty TEXT NOT NULL DEFAULT '0', filled_price TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, response_json TEXT
);
CREATE TABLE system_audit (
 id INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL,
 entity_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE bitcoin_observations (
 id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, kind TEXT NOT NULL,
 subject TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL,
 UNIQUE(observed_at,kind,subject)
);
CREATE INDEX bitcoin_observations_latest ON bitcoin_observations(kind,subject,observed_at DESC);
CREATE TABLE bitcoin_watch_addresses (
 address TEXT PRIMARY KEY, label TEXT NOT NULL, added_at TEXT NOT NULL,
 last_checked_at TEXT, next_check_at TEXT, failure_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE bitcoin_transactions (
 address TEXT NOT NULL REFERENCES bitcoin_watch_addresses(address) ON DELETE CASCADE,
 txid TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(address,txid)
);
CREATE TABLE system_commands (
 id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL REFERENCES system_deployments(id),
 action TEXT NOT NULL CHECK(action IN ('activate','pause','resume')),
 confirmation TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
 created_at TEXT NOT NULL, finished_at TEXT, error TEXT
);
CREATE TABLE bitcoin_watch_requests (
 id TEXT PRIMARY KEY, address TEXT NOT NULL, label TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL, error TEXT
);
CREATE TABLE system_stock_control (
 id INTEGER PRIMARY KEY CHECK(id=1), deployment_id TEXT NOT NULL REFERENCES system_deployments(id),
 activated_at TEXT NOT NULL
);
CREATE TABLE bitcoin_market_bars (
 bar_at TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(bar_at,observed_at)
);
