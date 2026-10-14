CREATE TABLE experiment_versions (
 id TEXT PRIMARY KEY, asset TEXT NOT NULL CHECK(asset IN ('stocks','bitcoin')),
 family TEXT NOT NULL, config_json TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TRIGGER experiment_versions_immutable BEFORE UPDATE ON experiment_versions
BEGIN SELECT RAISE(ABORT,'Experiment versions are immutable'); END;
CREATE TRIGGER experiment_versions_no_delete BEFORE DELETE ON experiment_versions
BEGIN SELECT RAISE(ABORT,'Experiment versions are immutable'); END;
CREATE TABLE experiment_batches (
 id TEXT PRIMARY KEY, asset TEXT NOT NULL, revision TEXT NOT NULL UNIQUE,
 plan_json TEXT NOT NULL, created TEXT NOT NULL, expires TEXT NOT NULL,
 account_id TEXT NOT NULL, approved TEXT, status TEXT NOT NULL DEFAULT 'preview',
 high_water TEXT NOT NULL DEFAULT '1000', day TEXT, day_equity TEXT,
 risk_reason TEXT, equity TEXT NOT NULL DEFAULT '1000', state_revision INTEGER NOT NULL DEFAULT 0,
 cash_anchor TEXT NOT NULL DEFAULT '1000',legacy_cash_anchor TEXT NOT NULL DEFAULT '0',experiment_cash_anchor TEXT NOT NULL DEFAULT '0'
);
CREATE UNIQUE INDEX experiment_active_asset ON experiment_batches(asset)
 WHERE status IN ('active','paused','exiting','expired');
CREATE TRIGGER experiment_batch_frozen BEFORE UPDATE OF revision,plan_json,created,expires,account_id,asset ON experiment_batches
BEGIN SELECT RAISE(ABORT,'Batch preview is frozen'); END;
CREATE TABLE experiment_instances (
 id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES experiment_batches(id),
 version_id TEXT NOT NULL REFERENCES experiment_versions(id),
 budget TEXT NOT NULL, cash TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'disabled', reason TEXT, last_decision TEXT,
 paused INTEGER NOT NULL DEFAULT 0, exit_requested INTEGER NOT NULL DEFAULT 0,
 UNIQUE(batch_id,version_id)
);
CREATE TABLE experiment_positions (
 instance_id TEXT NOT NULL REFERENCES experiment_instances(id), symbol TEXT NOT NULL,
 quantity TEXT NOT NULL DEFAULT '0', cost TEXT NOT NULL DEFAULT '0',
 entered TEXT, exit_due TEXT, cooldown_until TEXT, realized TEXT NOT NULL DEFAULT '0',
 PRIMARY KEY(instance_id,symbol)
);
CREATE TABLE experiment_decisions (
 id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES experiment_instances(id),
 symbol TEXT NOT NULL, bar_at TEXT NOT NULL, cutoff TEXT NOT NULL,
 observed TEXT NOT NULL, outcome TEXT NOT NULL, reason TEXT NOT NULL,
 evidence_json TEXT NOT NULL, UNIQUE(instance_id,symbol,bar_at)
);
CREATE INDEX experiment_decisions_page ON experiment_decisions(instance_id,cutoff DESC,id);
CREATE TABLE experiment_orders (
 id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES experiment_instances(id),
 account_id TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('buy','sell')),
 decision_id TEXT REFERENCES experiment_decisions(id), request_json TEXT NOT NULL,
 status TEXT NOT NULL, broker_id TEXT UNIQUE, created TEXT NOT NULL, updated TEXT NOT NULL,
 expires TEXT NOT NULL, reserved TEXT NOT NULL, filled_qty TEXT NOT NULL DEFAULT '0',
 filled_notional TEXT NOT NULL DEFAULT '0', reason TEXT NOT NULL,
 parent_id TEXT REFERENCES experiment_orders(id), response_json TEXT, error TEXT,
 qty_fee_adjustment TEXT NOT NULL DEFAULT '0',cash_fee_adjustment TEXT NOT NULL DEFAULT '0',reserve_evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX experiment_symbol_reservation ON experiment_orders(account_id,symbol)
 WHERE status NOT IN ('filled','canceled','expired','rejected');
CREATE INDEX experiment_orders_active ON experiment_orders(account_id,status);
CREATE INDEX experiment_orders_instance ON experiment_orders(instance_id,created);
CREATE TABLE experiment_fills (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES experiment_orders(id),
 at TEXT NOT NULL, quantity TEXT NOT NULL, notional TEXT NOT NULL,
 settlement_date TEXT, settled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX experiment_unsettled ON experiment_fills(settled,settlement_date);
CREATE TABLE experiment_fees (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, order_id TEXT REFERENCES experiment_orders(id),
 at TEXT NOT NULL, cash TEXT NOT NULL, quantity TEXT NOT NULL, payload_json TEXT NOT NULL,
 applied INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE experiment_broker_fills (
 account_id TEXT NOT NULL, id TEXT NOT NULL, broker_order_id TEXT NOT NULL,
 at TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL, notional TEXT NOT NULL,
 PRIMARY KEY(account_id,id)
);
CREATE INDEX experiment_broker_fills_order ON experiment_broker_fills(account_id,broker_order_id,at);
CREATE TABLE experiment_fee_receipts (
 account_id TEXT NOT NULL,id TEXT NOT NULL,payload_json TEXT NOT NULL,observed TEXT NOT NULL,
 applied INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(account_id,id)
);
CREATE TABLE experiment_commands (
 id TEXT PRIMARY KEY, asset TEXT NOT NULL, action TEXT NOT NULL,
 payload_json TEXT NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 result_json TEXT, completed TEXT
);
CREATE INDEX experiment_commands_pending ON experiment_commands(asset,status,created);
CREATE TABLE experiment_health (component TEXT PRIMARY KEY, at TEXT NOT NULL, error TEXT, detail_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE experiment_calendar (
 date TEXT PRIMARY KEY, opens TEXT NOT NULL, closes TEXT NOT NULL,
 settlement_date TEXT, observed TEXT NOT NULL
);
CREATE TABLE experiment_valuations (
 batch_id TEXT NOT NULL REFERENCES experiment_batches(id), at TEXT NOT NULL,
 equity TEXT NOT NULL, evidence_json TEXT NOT NULL, PRIMARY KEY(batch_id,at)
);
CREATE TABLE experiment_research_proposals (
 id TEXT PRIMARY KEY, asset TEXT NOT NULL, family TEXT NOT NULL, week TEXT NOT NULL,
 variant INTEGER NOT NULL CHECK(variant IN (1,2)), version_id TEXT NOT NULL REFERENCES experiment_versions(id),
 evidence_json TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(asset,family,week,variant)
);
CREATE TABLE execution_authority (asset TEXT PRIMARY KEY, owner TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0);
INSERT INTO execution_authority VALUES ('stocks','stock-owner-v1',0),('bitcoin','bitcoin-owner-v1',0);
CREATE TABLE execution_fill_events (
 id INTEGER PRIMARY KEY, ledger TEXT NOT NULL, order_id TEXT NOT NULL,
 at TEXT NOT NULL, quantity TEXT NOT NULL, notional TEXT NOT NULL
);
CREATE INDEX execution_fill_events_window ON execution_fill_events(at,ledger,order_id);
CREATE TRIGGER system_order_fill_delta AFTER UPDATE ON system_orders
WHEN CAST(NEW.filled_qty AS REAL)>CAST(OLD.filled_qty AS REAL)
BEGIN
 INSERT INTO execution_fill_events(ledger,order_id,at,quantity,notional)
 VALUES ('system',NEW.id,NEW.updated_at,
 CAST(NEW.filled_qty AS REAL)-CAST(OLD.filled_qty AS REAL),
 CAST(NEW.filled_qty AS REAL)*CAST(NEW.filled_price AS REAL)-CAST(OLD.filled_qty AS REAL)*COALESCE(CAST(OLD.filled_price AS REAL),0));
END;
CREATE INDEX IF NOT EXISTS experiment_paper_fills_time ON paper_fills(filled_at,order_id);
CREATE INDEX IF NOT EXISTS experiment_exit_fills_time ON paper_exit_fills(filled_at,exit_order_id);
CREATE INDEX IF NOT EXISTS experiment_btc_fills_time ON btc_fills(at,order_id);
CREATE TABLE btc_ledger_revisions (account_id TEXT PRIMARY KEY,revision INTEGER NOT NULL);
CREATE TABLE btc_reconciliation_cache (account_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload_json TEXT NOT NULL);
CREATE TRIGGER btc_totals_insert AFTER INSERT ON btc_orders BEGIN
 INSERT INTO btc_ledger_revisions VALUES (NEW.account_id,1) ON CONFLICT(account_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER btc_totals_update AFTER UPDATE ON btc_orders
WHEN NEW.filled_qty!=OLD.filled_qty OR NEW.filled_notional!=OLD.filled_notional OR NEW.fee_cash_adjustment!=OLD.fee_cash_adjustment OR NEW.fee_quantity_adjustment!=OLD.fee_quantity_adjustment
BEGIN INSERT INTO btc_ledger_revisions VALUES (NEW.account_id,1) ON CONFLICT(account_id) DO UPDATE SET revision=revision+1; END;
CREATE TRIGGER btc_totals_delete AFTER DELETE ON btc_orders BEGIN
 INSERT INTO btc_ledger_revisions VALUES (OLD.account_id,1) ON CONFLICT(account_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER btc_fees_totals_insert AFTER INSERT ON btc_fees BEGIN
 INSERT INTO btc_ledger_revisions VALUES (NEW.account_id,1) ON CONFLICT(account_id) DO UPDATE SET revision=revision+1;
END;
CREATE INDEX btc_recent_orders ON btc_orders(account_id,updated_at);
CREATE INDEX experiment_fill_time ON experiment_fills(at,order_id);
CREATE TABLE experiment_context (
 id TEXT PRIMARY KEY,source TEXT NOT NULL,symbol TEXT,title TEXT NOT NULL,
 url TEXT NOT NULL,published TEXT NOT NULL,observed TEXT NOT NULL
);
CREATE INDEX experiment_context_recent ON experiment_context(published DESC);
CREATE TABLE experiment_decision_gaps (
 instance_id TEXT NOT NULL REFERENCES experiment_instances(id),start TEXT NOT NULL,end TEXT NOT NULL,
 observed TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(instance_id,start,end)
);
CREATE TABLE experiment_stock_revision (id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL);
INSERT INTO experiment_stock_revision VALUES (1,0);
CREATE TABLE experiment_stock_cash_cache (id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,total TEXT NOT NULL);
CREATE TRIGGER experiment_stock_entry_cash AFTER INSERT ON paper_fills BEGIN UPDATE experiment_stock_revision SET revision=revision+1; END;
CREATE TRIGGER experiment_stock_exit_cash AFTER INSERT ON paper_exit_fills BEGIN UPDATE experiment_stock_revision SET revision=revision+1; END;
CREATE TRIGGER experiment_stock_system_cash AFTER UPDATE ON system_orders
WHEN NEW.filled_qty!=OLD.filled_qty OR NEW.filled_price IS NOT OLD.filled_price
BEGIN UPDATE experiment_stock_revision SET revision=revision+1; END;
CREATE TRIGGER experiment_stock_activity_cash AFTER INSERT ON broker_account_activities BEGIN UPDATE experiment_stock_revision SET revision=revision+1; END;
CREATE TRIGGER experiment_anchors_frozen BEFORE UPDATE OF cash_anchor,legacy_cash_anchor,experiment_cash_anchor ON experiment_batches
WHEN OLD.approved IS NOT NULL BEGIN SELECT RAISE(ABORT,'Approved cash anchors are immutable'); END;
CREATE TRIGGER experiment_stock_fee_receipt AFTER INSERT ON experiment_fee_receipts BEGIN UPDATE experiment_stock_revision SET revision=revision+1; END;
