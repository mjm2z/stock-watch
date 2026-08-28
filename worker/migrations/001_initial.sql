CREATE TABLE strategy_versions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('development', 'backtest', 'paper', 'retired')),
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    config_sha256 TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    promoted_at TEXT
) STRICT;

CREATE TABLE instruments (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT,
    exchange TEXT,
    asset_class TEXT NOT NULL DEFAULT 'us_equity',
    alpaca_asset_id TEXT,
    cik TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    fractionable INTEGER CHECK (fractionable IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, asset_class)
) STRICT;

CREATE TABLE universe_snapshots (
    id INTEGER PRIMARY KEY,
    universe TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    content_sha256 TEXT NOT NULL,
    survivorship_biased INTEGER NOT NULL DEFAULT 0 CHECK (survivorship_biased IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(universe, effective_at, content_sha256)
) STRICT;

CREATE TABLE universe_memberships (
    snapshot_id INTEGER NOT NULL REFERENCES universe_snapshots(id) ON DELETE CASCADE,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    PRIMARY KEY(snapshot_id, instrument_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE data_ingestions (
    id INTEGER PRIMARY KEY,
    dataset TEXT NOT NULL,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'partial')),
    version TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(dataset, provider, version)
) STRICT;

CREATE TABLE market_bars (
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    timestamp TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    trade_count INTEGER,
    vwap REAL,
    adjustment TEXT NOT NULL,
    provider TEXT NOT NULL,
    ingestion_id INTEGER REFERENCES data_ingestions(id),
    PRIMARY KEY(instrument_id, timestamp, timeframe, adjustment, provider)
) STRICT, WITHOUT ROWID;

CREATE INDEX market_bars_lookup
    ON market_bars(instrument_id, timeframe, timestamp);

CREATE TABLE fundamental_snapshots (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    as_of TEXT NOT NULL,
    filed_at TEXT NOT NULL,
    period_end TEXT NOT NULL,
    form TEXT NOT NULL,
    source_accession TEXT,
    facts_json TEXT NOT NULL CHECK (json_valid(facts_json)),
    provider TEXT NOT NULL DEFAULT 'sec',
    ingestion_id INTEGER REFERENCES data_ingestions(id),
    UNIQUE(instrument_id, filed_at, period_end, form, source_accession)
) STRICT;

CREATE INDEX fundamental_snapshots_point_in_time
    ON fundamental_snapshots(instrument_id, filed_at);

CREATE TABLE news_articles (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    published_at TEXT NOT NULL,
    updated_at TEXT,
    headline TEXT NOT NULL,
    summary TEXT,
    source TEXT,
    url TEXT,
    content_hash TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(raw_json)),
    ingestion_id INTEGER REFERENCES data_ingestions(id),
    UNIQUE(provider, content_hash)
) STRICT;

CREATE INDEX news_articles_published_at ON news_articles(published_at);

CREATE TABLE news_instruments (
    news_id TEXT NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    relevance REAL,
    sentiment REAL,
    sentiment_model TEXT,
    PRIMARY KEY(news_id, instrument_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE feature_snapshots (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    as_of TEXT NOT NULL,
    feature_set_version TEXT NOT NULL,
    features_json TEXT NOT NULL CHECK (json_valid(features_json)),
    data_completeness REAL NOT NULL CHECK (data_completeness BETWEEN 0 AND 100),
    source_refs_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(source_refs_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instrument_id, as_of, feature_set_version)
) STRICT;

CREATE TABLE scan_runs (
    id TEXT PRIMARY KEY,
    strategy_version_id TEXT NOT NULL REFERENCES strategy_versions(id),
    universe_snapshot_id INTEGER NOT NULL REFERENCES universe_snapshots(id),
    scan_type TEXT NOT NULL CHECK (scan_type IN ('open', 'close', 'manual', 'backtest')),
    scheduled_for TEXT NOT NULL,
    data_cutoff TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'partial')),
    survivorship_biased INTEGER NOT NULL DEFAULT 0 CHECK (survivorship_biased IN (0, 1)),
    error TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metrics_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(strategy_version_id, scan_type, scheduled_for)
) STRICT;

CREATE TABLE signals (
    id TEXT PRIMARY KEY,
    scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
    strategy_version_id TEXT NOT NULL REFERENCES strategy_versions(id),
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    feature_snapshot_id INTEGER NOT NULL REFERENCES feature_snapshots(id),
    horizon_trading_days INTEGER NOT NULL CHECK (horizon_trading_days IN (5, 21, 63, 105)),
    as_of TEXT NOT NULL,
    opportunity_score REAL NOT NULL CHECK (opportunity_score BETWEEN 0 AND 100),
    data_completeness REAL NOT NULL CHECK (data_completeness BETWEEN 0 AND 100),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    probability_positive REAL CHECK (probability_positive BETWEEN 0 AND 1),
    probability_beat_spy REAL CHECK (probability_beat_spy BETWEEN 0 AND 1),
    decision TEXT NOT NULL CHECK (decision IN ('qualified', 'rejected', 'duplicate', 'risk_veto')),
    reasons_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(reasons_json)),
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scan_run_id, instrument_id, horizon_trading_days)
) STRICT;

CREATE INDEX signals_ranked
    ON signals(scan_run_id, decision, opportunity_score DESC);
CREATE INDEX signals_instrument_history
    ON signals(instrument_id, as_of DESC);

CREATE TABLE signal_components (
    signal_id TEXT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    raw_value REAL,
    normalized_score REAL CHECK (normalized_score BETWEEN 0 AND 100),
    weight REAL NOT NULL CHECK (weight > 0 AND weight <= 1),
    weighted_points REAL NOT NULL,
    available INTEGER NOT NULL CHECK (available IN (0, 1)),
    source_refs_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(source_refs_json)),
    PRIMARY KEY(signal_id, name)
) STRICT, WITHOUT ROWID;

CREATE TABLE paper_orders (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL REFERENCES signals(id),
    client_order_id TEXT NOT NULL UNIQUE,
    broker TEXT NOT NULL DEFAULT 'alpaca',
    broker_order_id TEXT UNIQUE,
    broker_request_id TEXT,
    side TEXT NOT NULL CHECK (side = 'buy'),
    order_type TEXT NOT NULL CHECK (order_type IN ('market', 'limit')),
    time_in_force TEXT NOT NULL,
    notional_usd REAL NOT NULL CHECK (notional_usd >= 5 AND notional_usd <= 15),
    limit_price REAL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'submitted', 'accepted', 'partially_filled', 'filled', 'canceled', 'rejected', 'error')),
    submitted_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(raw_json))
) STRICT;

CREATE TABLE paper_fills (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES paper_orders(id),
    broker_fill_id TEXT,
    filled_at TEXT NOT NULL,
    quantity REAL NOT NULL CHECK (quantity > 0),
    price REAL NOT NULL CHECK (price > 0),
    notional_usd REAL NOT NULL CHECK (notional_usd > 0),
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(raw_json)),
    UNIQUE(order_id, broker_fill_id)
) STRICT;

CREATE TABLE paper_trade_lots (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL UNIQUE REFERENCES signals(id),
    strategy_version_id TEXT NOT NULL REFERENCES strategy_versions(id),
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    horizon_trading_days INTEGER NOT NULL CHECK (horizon_trading_days IN (5, 21, 63, 105)),
    entry_order_id TEXT NOT NULL UNIQUE REFERENCES paper_orders(id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'open', 'closing', 'closed', 'canceled', 'error')),
    opened_at TEXT,
    minimum_exit_at TEXT,
    target_exit_at TEXT,
    closed_at TEXT,
    entry_quantity REAL CHECK (entry_quantity > 0),
    entry_price REAL CHECK (entry_price > 0),
    entry_notional_usd REAL NOT NULL CHECK (entry_notional_usd >= 5 AND entry_notional_usd <= 15),
    exit_quantity REAL,
    exit_price REAL,
    realized_return REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE UNIQUE INDEX one_open_lot_per_ticker_horizon_strategy
    ON paper_trade_lots(instrument_id, horizon_trading_days, strategy_version_id)
    WHERE status IN ('pending', 'open', 'closing');

CREATE TABLE signal_outcomes (
    signal_id TEXT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    horizon_trading_days INTEGER NOT NULL CHECK (horizon_trading_days IN (5, 21, 63, 105)),
    observed_at TEXT NOT NULL,
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    terminal_price REAL NOT NULL CHECK (terminal_price > 0),
    gross_return REAL NOT NULL,
    modeled_cost_return REAL NOT NULL DEFAULT 0,
    net_return REAL NOT NULL,
    terminal_positive INTEGER NOT NULL CHECK (terminal_positive IN (0, 1)),
    terminal_at_least_5 INTEGER NOT NULL CHECK (terminal_at_least_5 IN (0, 1)),
    terminal_at_least_10 INTEGER NOT NULL CHECK (terminal_at_least_10 IN (0, 1)),
    touched_5 INTEGER NOT NULL CHECK (touched_5 IN (0, 1)),
    touched_10 INTEGER NOT NULL CHECK (touched_10 IN (0, 1)),
    spy_return REAL NOT NULL,
    excess_return REAL NOT NULL,
    beat_spy INTEGER NOT NULL CHECK (beat_spy IN (0, 1)),
    maximum_favorable_excursion REAL NOT NULL,
    maximum_adverse_excursion REAL NOT NULL,
    provider TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    PRIMARY KEY(signal_id, horizon_trading_days)
) STRICT, WITHOUT ROWID;

CREATE TABLE portfolio_snapshots (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL UNIQUE,
    cash REAL NOT NULL,
    market_value REAL NOT NULL,
    equity REAL NOT NULL,
    gross_exposure REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    spy_value REAL,
    source TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(raw_json))
) STRICT;

CREATE TABLE job_runs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    scheduled_for TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')),
    attempt INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE INDEX job_runs_due ON job_runs(status, scheduled_for);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json))
) STRICT;

CREATE INDEX audit_events_entity
    ON audit_events(entity_type, entity_id, occurred_at);
