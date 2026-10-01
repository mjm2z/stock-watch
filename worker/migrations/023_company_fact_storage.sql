-- Keep every observation/id, but store identical SEC document bodies once.
-- The installer takes a verified full recovery copy and stops writers first.
ALTER TABLE company_fact_documents RENAME TO company_fact_documents_legacy;
DROP INDEX company_fact_documents_point_in_time;

CREATE TABLE company_fact_contents (
    content_sha256 TEXT PRIMARY KEY,
    facts_json TEXT NOT NULL CHECK (json_valid(facts_json))
) STRICT;

INSERT INTO company_fact_contents(content_sha256, facts_json)
SELECT content_sha256, facts_json FROM company_fact_documents_legacy
WHERE id IN (SELECT MIN(id) FROM company_fact_documents_legacy GROUP BY content_sha256);

-- Fail atomically if an old hash is attached to different payloads. Never
-- silently choose one version of conflicting historical evidence.
CREATE TEMP TABLE company_fact_storage_guard (valid INTEGER CHECK (valid = 1));
INSERT INTO company_fact_storage_guard
SELECT NOT EXISTS (
    SELECT 1 FROM company_fact_documents_legacy AS old
    JOIN company_fact_contents AS content USING(content_sha256)
    WHERE old.facts_json != content.facts_json
);

CREATE TABLE company_fact_observations (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    captured_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL REFERENCES company_fact_contents(content_sha256),
    provider TEXT NOT NULL DEFAULT 'sec',
    ingestion_id INTEGER REFERENCES data_ingestions(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instrument_id, captured_at, provider)
) STRICT;
INSERT INTO company_fact_observations
SELECT id, instrument_id, captured_at, content_sha256, provider, ingestion_id, created_at
FROM company_fact_documents_legacy;
CREATE INDEX company_fact_observations_point_in_time
ON company_fact_observations(instrument_id, captured_at DESC);

-- Preserve the historical read interface, including document IDs recorded in
-- signals and datasets. Payloads are joined only when callers request them.
CREATE VIEW company_fact_documents AS
SELECT observation.id, observation.instrument_id, observation.captured_at,
       observation.content_sha256, content.facts_json, observation.provider,
       observation.ingestion_id, observation.created_at
FROM company_fact_observations AS observation
JOIN company_fact_contents AS content USING(content_sha256);

INSERT INTO company_fact_storage_guard
SELECT (SELECT COUNT(*) FROM company_fact_documents_legacy) =
       (SELECT COUNT(*) FROM company_fact_documents);
DROP TABLE company_fact_documents_legacy;
DROP TABLE company_fact_storage_guard;

-- Support explicit SQL fixture/import inserts through the historical interface.
-- Application writes use the underlying tables to obtain real lastrowid values.
CREATE TRIGGER company_fact_documents_insert INSTEAD OF INSERT ON company_fact_documents
BEGIN
    SELECT RAISE(ABORT, 'CompanyFacts content hash conflict') WHERE EXISTS (
        SELECT 1 FROM company_fact_contents
        WHERE content_sha256 = NEW.content_sha256 AND facts_json != NEW.facts_json
    );
    INSERT INTO company_fact_contents(content_sha256, facts_json)
    VALUES(NEW.content_sha256, NEW.facts_json) ON CONFLICT DO NOTHING;
    INSERT INTO company_fact_observations(id, instrument_id, captured_at, content_sha256,
                                          provider, ingestion_id, created_at)
    VALUES(NEW.id, NEW.instrument_id, NEW.captured_at, NEW.content_sha256,
           COALESCE(NEW.provider, 'sec'), NEW.ingestion_id,
           COALESCE(NEW.created_at, CURRENT_TIMESTAMP));
END;
