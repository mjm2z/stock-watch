-- Additive research/control metadata. Existing ledgers and authority are untouched.
CREATE TABLE research_policies (
 id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, discovery_enabled INTEGER NOT NULL DEFAULT 1,
 threshold REAL NOT NULL CHECK(threshold>=0.8 AND threshold<=1),
 pool TEXT NOT NULL, sleeve TEXT NOT NULL, entry_cap TEXT NOT NULL,
 reason TEXT NOT NULL
);
INSERT INTO research_policies(created_at,threshold,pool,sleeve,entry_cap,reason)
 VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),.8,'1000','200','100','User-approved experimental Bitcoin paper policy; 100 scenarios; no 30-day prerequisite');
CREATE TABLE research_lineage (
 version_id TEXT PRIMARY KEY REFERENCES system_versions(id), parent_version TEXT REFERENCES system_versions(id),
 parent_run TEXT, thesis TEXT NOT NULL DEFAULT '', changes_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE research_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, asset TEXT NOT NULL,
 kind TEXT NOT NULL, entity_id TEXT, payload_json TEXT NOT NULL
);
CREATE INDEX research_events_recent ON research_events(asset,id DESC);
CREATE TABLE research_metrics (
 run_id TEXT PRIMARY KEY REFERENCES system_runs(id), version TEXT NOT NULL,
 payload_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE discovery_batches (
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', consumed_seconds REAL NOT NULL DEFAULT 0,
 summary_json TEXT NOT NULL DEFAULT '{}', error TEXT
);
CREATE TABLE discovery_trials (
 id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES discovery_batches(id),
 version_id TEXT NOT NULL REFERENCES system_versions(id), asset TEXT NOT NULL,
 dataset_id TEXT REFERENCES system_datasets(id), policy_id INTEGER NOT NULL REFERENCES research_policies(id),
 budget TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', stage TEXT NOT NULL DEFAULT 'Waiting for data',
 heartbeat_at TEXT, created_at TEXT NOT NULL, finished_at TEXT, expires_at TEXT,
 result_json TEXT, error TEXT, source TEXT NOT NULL DEFAULT 'scheduled',
 UNIQUE(version_id,dataset_id,policy_id,budget)
);
CREATE TABLE discovery_scenarios (
 trial_id TEXT NOT NULL REFERENCES discovery_trials(id), window_index INTEGER NOT NULL,
 profile TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
 result_json TEXT NOT NULL, PRIMARY KEY(trial_id,window_index,profile)
);
CREATE TABLE paper_authorizations (
 version_id TEXT PRIMARY KEY REFERENCES system_versions(id), trial_id TEXT NOT NULL REFERENCES discovery_trials(id),
 policy_id INTEGER NOT NULL REFERENCES research_policies(id), approved_at TEXT NOT NULL,
 budget TEXT NOT NULL, account_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE research_proposals (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL, excerpt TEXT NOT NULL,
 published_at TEXT, retrieved_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'inbox',
 version_id TEXT REFERENCES system_versions(id)
);
CREATE TABLE research_job_stages (
 job_id TEXT PRIMARY KEY, stage TEXT NOT NULL, heartbeat_at TEXT NOT NULL
);
CREATE TABLE paper_cashflows (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES btc_accounts(id),
 amount TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL
);
