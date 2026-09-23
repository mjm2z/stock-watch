-- Shared research uses the existing SQLite backup and restore pipeline.
CREATE TABLE research_watchlist (
    ticker TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
) STRICT;
CREATE TABLE research_notes (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    created_at TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    evidence TEXT NOT NULL,
    contrary_evidence TEXT NOT NULL,
    horizon INTEGER NOT NULL CHECK(horizon IN (5,21,63,105)),
    review_on TEXT NOT NULL,
    assessment TEXT NOT NULL CHECK(assessment IN ('open','supported','mixed','invalidated'))
) STRICT;
CREATE INDEX research_notes_ticker_date ON research_notes(ticker, created_at DESC);
