-- Additive measurement/provenance only. No strategy or execution authority changes.
CREATE TABLE market_series (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, feed TEXT NOT NULL,
 venue TEXT NOT NULL, adjustment TEXT NOT NULL, timeframe TEXT NOT NULL,
 UNIQUE(provider,feed,venue,adjustment,timeframe)
);
CREATE TABLE market_observations (
 series_id TEXT NOT NULL REFERENCES market_series(id), instrument_id INTEGER NOT NULL REFERENCES instruments(id),
 timestamp TEXT NOT NULL, observed_at TEXT NOT NULL, available_at TEXT,
 content_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 ingestion_id INTEGER REFERENCES data_ingestions(id),
 PRIMARY KEY(series_id,instrument_id,timestamp,content_sha256)
);
CREATE INDEX market_observations_lookup ON market_observations(series_id,instrument_id,timestamp);
CREATE TABLE source_provenance (
 entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, recorded_at TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), PRIMARY KEY(entity_type,entity_id)
);
CREATE INDEX source_provenance_latest ON source_provenance(entity_type,recorded_at DESC);
CREATE TABLE scan_diagnostic_snapshots (
 scan_id TEXT PRIMARY KEY REFERENCES scan_runs(id), method TEXT NOT NULL,
 captured_at TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
CREATE TABLE performance_marks (
 scope TEXT NOT NULL, owner_id TEXT NOT NULL, at TEXT NOT NULL,
 equity TEXT NOT NULL, cash TEXT NOT NULL, external_flow TEXT NOT NULL DEFAULT '0',
 flow_coverage INTEGER NOT NULL DEFAULT 0, valuation_complete INTEGER NOT NULL DEFAULT 0,
 details_json TEXT NOT NULL CHECK(json_valid(details_json)),
 PRIMARY KEY(scope,owner_id,at)
);
CREATE TABLE performance_results (
 scope TEXT NOT NULL, owner_id TEXT NOT NULL, method TEXT NOT NULL,
 as_of TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 PRIMARY KEY(scope,owner_id,method)
);
