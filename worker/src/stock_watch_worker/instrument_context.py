"""Sector metadata from the already approved, validated universe CSV."""
import csv
import io
import json

SECTORS = {'Communication Services','Consumer Discretionary','Consumer Staples','Energy',
           'Financials','Health Care','Industrials','Information Technology','Materials',
           'Real Estate','Utilities'}
ALIASES = {'Healthcare':'Health Care','Technology':'Information Technology'}

def update_sectors(connection, csv_text, *, captured_at, source):
    reader=csv.DictReader(io.StringIO(csv_text.lstrip('\ufeff')))
    fields={key.lower().strip():key for key in (reader.fieldnames or [])}
    symbol_key=fields.get('symbol') or fields.get('ticker')
    sector_key=fields.get('gics sector') or fields.get('sector')
    if not symbol_key or not sector_key:
        return 0
    records={}
    for row in reader:
        symbol=row[symbol_key].strip().upper()
        sector=row[sector_key].strip()
        sector=ALIASES.get(sector,sector)
        if sector not in SECTORS:
            continue
        if symbol in records and records[symbol]!=sector:
            raise ValueError('Conflicting sector metadata')
        records[symbol]=sector
    count=0
    with connection:
        for symbol,sector in records.items():
            instrument=connection.execute('SELECT id FROM instruments WHERE symbol=?',(symbol,)).fetchone()
            if not instrument:continue
            connection.execute('''INSERT INTO instrument_context(instrument_id,sector,captured_at,source)
                VALUES (?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET sector=excluded.sector,
                captured_at=excluded.captured_at,source=excluded.source''',(instrument[0],sector,captured_at,source))
            count+=1
        connection.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,payload_json) VALUES ('sector_metadata_refreshed','universe','sp500',?)",
                           (json.dumps({'classified':count,'source':source,'captured_at':captured_at}),))
    return count
