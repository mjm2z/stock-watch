CREATE TABLE market_sessions (
    trading_date TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider = 'alpaca-paper'),
    opens_at TEXT NOT NULL,
    closes_at TEXT NOT NULL,
    ingestion_id INTEGER REFERENCES data_ingestions(id),
    PRIMARY KEY (trading_date, provider),
    CHECK (opens_at < closes_at)
) STRICT, WITHOUT ROWID;

CREATE INDEX market_sessions_close_time
    ON market_sessions(closes_at);
