BEGIN IMMEDIATE;
CREATE TABLE assessment_reviews (
    signal_id TEXT PRIMARY KEY REFERENCES signals(id),
    assessed_at TEXT NOT NULL,
    quality_json TEXT NOT NULL CHECK(json_valid(quality_json)),
    source_version TEXT NOT NULL
) STRICT;
CREATE TABLE shadow_assessments (
    signal_id TEXT NOT NULL REFERENCES signals(id),
    variant TEXT NOT NULL,
    score REAL NOT NULL,
    qualified INTEGER NOT NULL CHECK(qualified IN (0,1)),
    reasons_json TEXT NOT NULL CHECK(json_valid(reasons_json)),
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY(signal_id,variant)
) STRICT;
CREATE TABLE entry_checks (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES paper_orders(id),
    checked_at TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('allow','defer','reject')),
    reason TEXT NOT NULL,
    details_json TEXT NOT NULL CHECK(json_valid(details_json))
) STRICT;
CREATE INDEX entry_checks_order ON entry_checks(order_id,checked_at DESC);
CREATE TABLE instrument_context (
    instrument_id INTEGER PRIMARY KEY REFERENCES instruments(id),
    sector TEXT,
    earnings_at TEXT,
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL
) STRICT;
CREATE TABLE deferred_entries (
    order_id TEXT PRIMARY KEY REFERENCES paper_orders(id),
    next_check_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    reference_price REAL NOT NULL CHECK(reference_price>0),
    state TEXT NOT NULL DEFAULT 'waiting' CHECK(state IN ('waiting','submitted','rejected'))
) STRICT;
COMMIT;
