"""Read-only input inspection; collection, execution and qualification stay separate."""
from pathlib import Path

SQL = Path(__file__).with_suffix('.sql').read_text()


def stock_prerequisites(db, start='1900-01-01T00:00:00Z', end='9999-01-01T00:00:00Z'):
    cursor = db.execute(SQL, {'start': start, 'end': end})
    row = dict(zip((column[0] for column in cursor.description), cursor.fetchone()))
    blockers = []
    if not row['instruments']:
        blockers.append('No captured stock universe members')
    if not row['rawBars']:
        blockers.append('Raw daily bars are missing; adjusted scanner bars cannot substitute')
    if not row['requestedSessions']:
        blockers.append('No captured exchange sessions cover this requested interval')
    if row['instruments'] and row['missingSectors'] == row['instruments']:
        blockers.append('Sector metadata is missing for all universe members')
    if row['ambiguousSessions']:
        blockers.append('Multiple raw daily sources cover the same symbol/session; select a canonical source')
    if not row['usableBars']:
        blockers.append('No raw bars join sector and calendar data in this requested interval')
    return {**row, 'blockers': blockers, 'canPrepare': not blockers}


def require_stock_inputs(db, start='1900-01-01T00:00:00Z', end='9999-01-01T00:00:00Z'):
    result = stock_prerequisites(db, start, end)
    if not result['canPrepare']:
        raise ValueError('Stock data prerequisites: ' + '; '.join(result['blockers']))
    return result
