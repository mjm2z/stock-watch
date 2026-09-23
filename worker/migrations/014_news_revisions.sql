-- Preserve the original article/links for existing feature references and rollback.
CREATE TABLE news_revisions (
    id INTEGER PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES news_articles(id),
    content_hash TEXT NOT NULL,
    published_at TEXT NOT NULL,
    available_at TEXT NOT NULL,
    first_observed_at TEXT,
    headline TEXT NOT NULL,
    summary TEXT,
    raw_json TEXT NOT NULL CHECK (json_valid(raw_json)),
    UNIQUE(article_id, content_hash)
) STRICT;
CREATE INDEX news_revisions_cutoff ON news_revisions(available_at, article_id);
CREATE TABLE news_revision_instruments (
    revision_id INTEGER NOT NULL REFERENCES news_revisions(id),
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    sentiment REAL NOT NULL,
    sentiment_model TEXT NOT NULL,
    PRIMARY KEY(revision_id, instrument_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE news_revision_observations (
    ingestion_id INTEGER NOT NULL REFERENCES data_ingestions(id),
    revision_id INTEGER NOT NULL REFERENCES news_revisions(id),
    PRIMARY KEY(ingestion_id, revision_id)
) STRICT, WITHOUT ROWID;
INSERT INTO news_revisions(article_id,content_hash,published_at,available_at,
    first_observed_at,headline,summary,raw_json)
SELECT a.id,a.content_hash,a.published_at,COALESCE(a.updated_at,a.published_at),
    d.completed_at,a.headline,a.summary,a.raw_json
FROM news_articles a LEFT JOIN data_ingestions d ON d.id=a.ingestion_id;
INSERT INTO news_revision_instruments
SELECT r.id,l.instrument_id,l.sentiment,l.sentiment_model
FROM news_instruments l JOIN news_revisions r ON r.article_id=l.news_id
WHERE l.sentiment IS NOT NULL AND l.sentiment_model IS NOT NULL;
INSERT INTO news_revision_observations
SELECT a.ingestion_id,r.id FROM news_articles a JOIN news_revisions r ON r.article_id=a.id
WHERE a.ingestion_id IS NOT NULL;
-- A header also freezes an empty news selection.
CREATE TABLE scan_news_snapshots (
    scan_run_id TEXT PRIMARY KEY REFERENCES scan_runs(id),
    frozen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cutoff_policy TEXT NOT NULL
) STRICT;
CREATE TABLE scan_news_revisions (
    scan_run_id TEXT NOT NULL REFERENCES scan_news_snapshots(scan_run_id),
    revision_id INTEGER NOT NULL REFERENCES news_revisions(id),
    PRIMARY KEY(scan_run_id,revision_id)
) STRICT, WITHOUT ROWID;
