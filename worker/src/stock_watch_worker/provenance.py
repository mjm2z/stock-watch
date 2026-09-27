"""Immutable source identity; legacy observations are never assigned guessed feeds."""
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone


def present(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def record_source(db, kind, identifier, payload):
    if not present(db, 'source_provenance'):
        return
    value = canonical(payload)
    old = db.execute('SELECT payload_json FROM source_provenance WHERE entity_type=? AND entity_id=?',
                     (kind, str(identifier))).fetchone()
    if old and old[0] != value:
        raise ValueError('Frozen source provenance changed')
    db.execute('INSERT OR IGNORE INTO source_provenance VALUES (?,?,?,?)',
               (kind, str(identifier), datetime.now(timezone.utc).isoformat(), value))


def persist_series(db, bars, symbol_ids, *, provider, feed, adjustment, timeframe, ingestion_id):
    if not present(db, 'market_series'):
        if feed not in ('iex', 'unknown'):
            raise ValueError('Install provenance migration before collecting another stock feed')
        return None
    venue = 'IEX' if feed == 'iex' else 'US consolidated' if feed in ('sip', 'delayed_sip') else 'Unknown'
    metadata = dict(provider=provider, feed=feed, venue=venue, adjustment=adjustment, timeframe=timeframe)
    series = hashlib.sha256(canonical(metadata).encode()).hexdigest()
    db.execute('INSERT OR IGNORE INTO market_series VALUES (?,?,?,?,?,?)',
               (series, provider, feed, venue, adjustment, timeframe))
    if ingestion_id is not None:
        record_source(db, 'ingestion', ingestion_id, {**metadata, 'series_id': series,
                      'availability': 'retrieval observed; historical publication timing not verified'})
    # Frozen scan responses and legacy revision records already retain IEX payloads.
    # Other feeds live only in the separate series store, never in the legacy key.
    if feed not in ('iex', 'unknown'):
        inserted = 0
        for bar in bars:
            payload = canonical(asdict(bar))
            digest = hashlib.sha256(payload.encode()).hexdigest()
            cursor = db.execute('INSERT OR IGNORE INTO market_observations VALUES (?,?,?,?,NULL,?,?,?)',
                (series, symbol_ids[bar.symbol], bar.timestamp, datetime.now(timezone.utc).isoformat(),
                 digest, payload, ingestion_id))
            inserted += cursor.rowcount
        return inserted
    return None
