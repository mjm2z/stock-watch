-- Research snapshots are deliberately outside the executable version registry.
ALTER TABLE workspace_drafts ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
CREATE TABLE research_snapshots (
 id TEXT PRIMARY KEY, asset TEXT NOT NULL, draft_id TEXT, draft_revision INTEGER,
 config_json TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER research_snapshot_immutable BEFORE UPDATE ON research_snapshots
 BEGIN SELECT RAISE(ABORT,'Research snapshots are immutable'); END;
CREATE TABLE research_previews (
 id TEXT PRIMARY KEY REFERENCES workspace_jobs(id), snapshot_id TEXT NOT NULL REFERENCES research_snapshots(id),
 dataset_id TEXT REFERENCES system_datasets(id), identity TEXT, result_json TEXT, created_at TEXT NOT NULL
);
CREATE INDEX research_preview_identity ON research_previews(identity);
CREATE INDEX research_preview_artifact ON research_previews(json_extract(result_json,'$.artifact_sha256'));
CREATE TABLE research_experiments (
 id TEXT PRIMARY KEY, asset TEXT NOT NULL, parent_id TEXT REFERENCES research_experiments(id),
 plan_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER research_experiment_immutable BEFORE UPDATE ON research_experiments
 BEGIN SELECT RAISE(ABORT,'Amend an experiment by creating a linked revision'); END;
CREATE TABLE research_attempts (
 id TEXT PRIMARY KEY REFERENCES workspace_jobs(id), experiment_id TEXT NOT NULL REFERENCES research_experiments(id),
 snapshot_id TEXT NOT NULL REFERENCES research_snapshots(id), role TEXT NOT NULL CHECK(role IN ('baseline','candidate')),
 reused_from TEXT, created_at TEXT NOT NULL
);
CREATE TABLE research_reviews (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES research_experiments(id),
 conclusion TEXT NOT NULL, explanation TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE research_access (
 id INTEGER PRIMARY KEY, asset TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES research_snapshots(id),
 dataset_id TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, purpose TEXT NOT NULL, at TEXT NOT NULL
);
CREATE INDEX research_access_interval ON research_access(asset,starts_at,ends_at);
-- Retain future state changes without rewriting legacy orders or making up their history.
CREATE TABLE workspace_activity (
 id INTEGER PRIMARY KEY, asset TEXT NOT NULL, account_id TEXT NOT NULL, owner TEXT NOT NULL,
 symbol TEXT NOT NULL, entity_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
 at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX workspace_activity_scope ON workspace_activity(asset,symbol,id DESC);
CREATE TRIGGER btc_activity_insert AFTER INSERT ON btc_orders BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 VALUES('bitcoin',NEW.account_id,NEW.version_id,'BTC/USD',NEW.id,'intent',NEW.status,NEW.created_at,
 json_object('quantity',NEW.quantity,'side',NEW.side,'reason',NEW.reason,'reference_price',NEW.reference_price));
END;
CREATE TRIGGER btc_activity_update AFTER UPDATE ON btc_orders
WHEN OLD.status != NEW.status OR OLD.filled_qty != NEW.filled_qty BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 VALUES('bitcoin',NEW.account_id,NEW.version_id,'BTC/USD',NEW.id,
 CASE WHEN OLD.filled_qty != NEW.filled_qty THEN 'fill' ELSE 'status' END,NEW.status,NEW.updated_at,
 json_object('side',NEW.side,'filled_qty',NEW.filled_qty,'filled_notional',NEW.filled_notional,'broker_id',NEW.broker_id,'reason',NEW.reason));
END;
CREATE TRIGGER system_activity_insert AFTER INSERT ON system_orders BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 SELECT v.asset,COALESCE(d.account_id,'shadow'),d.version_id,NEW.symbol,NEW.id,'intent',NEW.status,NEW.created_at,NEW.request_json
 FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE d.id=NEW.deployment_id;
END;
CREATE TRIGGER system_activity_update AFTER UPDATE ON system_orders
WHEN OLD.status != NEW.status OR OLD.filled_qty != NEW.filled_qty BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 SELECT v.asset,COALESCE(d.account_id,'shadow'),d.version_id,NEW.symbol,NEW.id,
 CASE WHEN OLD.filled_qty != NEW.filled_qty THEN 'fill' ELSE 'status' END,NEW.status,NEW.updated_at,
 json_object('side',NEW.side,'filled_qty',NEW.filled_qty,'filled_price',NEW.filled_price,'broker_id',NEW.broker_id)
 FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE d.id=NEW.deployment_id;
END;
CREATE TRIGGER scanner_activity_insert AFTER INSERT ON paper_orders BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 SELECT 'stocks','automated-stocks','legacy-scanner',i.symbol,NEW.id,'intent',NEW.status,NEW.updated_at,
 json_object('notional',NEW.notional_usd,'type',NEW.order_type,'limit_price',NEW.limit_price)
 FROM signals s JOIN instruments i ON i.id=s.instrument_id WHERE s.id=NEW.signal_id;
END;
CREATE TRIGGER scanner_activity_update AFTER UPDATE OF status ON paper_orders WHEN OLD.status != NEW.status BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 SELECT 'stocks','automated-stocks','legacy-scanner',i.symbol,NEW.id,'status',NEW.status,NEW.updated_at,
 json_object('broker_id',NEW.broker_order_id,'error',NEW.error)
 FROM signals s JOIN instruments i ON i.id=s.instrument_id WHERE s.id=NEW.signal_id;
END;
CREATE TRIGGER scanner_exit_activity AFTER UPDATE OF status ON paper_exit_orders WHEN OLD.status != NEW.status BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 SELECT 'stocks','automated-stocks','legacy-scanner',i.symbol,NEW.id,'exit',NEW.status,NEW.updated_at,
 json_object('broker_id',NEW.broker_order_id,'quantity',NEW.quantity,'lot',NEW.lot_id,'error',NEW.error)
 FROM paper_trade_lots l JOIN instruments i ON i.id=l.instrument_id WHERE l.id=NEW.lot_id;
END;
CREATE TRIGGER scanner_fill_activity AFTER INSERT ON paper_fills BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 SELECT 'stocks','automated-stocks','legacy-scanner',i.symbol,NEW.order_id,'fill',o.status,NEW.filled_at,
 json_object('fill_id',NEW.id,'quantity',NEW.quantity,'price',NEW.price,'notional',NEW.notional_usd)
 FROM paper_orders o JOIN signals s ON s.id=o.signal_id JOIN instruments i ON i.id=s.instrument_id WHERE o.id=NEW.order_id;
END;
CREATE TRIGGER scanner_exit_fill_activity AFTER INSERT ON paper_exit_fills BEGIN
 INSERT INTO workspace_activity(asset,account_id,owner,symbol,entity_id,kind,status,at,payload_json)
 SELECT 'stocks','automated-stocks','legacy-scanner',i.symbol,NEW.exit_order_id,'exit_fill',o.status,NEW.filled_at,
 json_object('fill_id',NEW.id,'quantity',NEW.quantity,'price',NEW.price,'notional',NEW.notional_usd)
 FROM paper_exit_orders o JOIN paper_trade_lots l ON l.id=o.lot_id JOIN instruments i ON i.id=l.instrument_id WHERE o.id=NEW.exit_order_id;
END;
