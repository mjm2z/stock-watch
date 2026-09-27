#!/usr/bin/env python3
"""Bounded read-only release inspection. No trading CLI, writes, or recovery scans.

Use the protected service environment with --broker-readonly for GET-only paper
broker observations. Output excludes credentials and broker account/order IDs.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def capture(action):
    try:
        return {'available': True, 'result': action()}
    except Exception as error:
        # Exception bodies/URLs can contain broker responses or private paths.
        return {'available': False, 'error_type': type(error).__name__}


def get_json(url, headers=None):
    request = Request(url, headers=headers or {}, method='GET')
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Response exceeds bounded report size')
        return response.status, json.loads(raw)


def readiness():
    status, body = get_json('http://127.0.0.1:3001/api/systems/health')
    return {'http_status': status, 'healthy': body.get('healthy'),
            'checks': [{k: row.get(k) for k in
                        ('worker', 'state', 'healthy', 'ageSeconds', 'nextAt', 'blocked')}
                       for row in body.get('checks', [])]}


def availability():
    status, body = get_json('http://127.0.0.1:3001/api/health')
    return {'http_status': status, **{key: body.get(key) for key in
            ('status', 'generatedAt', 'strategyStatus', 'latestScan', 'brokerReconciliation')}}


def services():
    names = ['web', 'worker', 'dispatch', 'exits', 'maintenance', 'discovery',
             'bitcoin-automation', 'bitcoin-trading', 'bitcoin-data', 'systems-stocks']
    units = [f'stock-watch-{name}.{suffix}' for name in names
             for suffix in (('service',) if name == 'web' else ('service', 'timer'))]
    result = subprocess.run(['systemctl', 'show', *units,
        '--property=Id,LoadState,ActiveState,UnitFileState,Result,ExecMainStatus,ExecMainExitTimestamp,LastTriggerUSec,NextElapseUSecRealtime'],
        check=True, capture_output=True, text=True, timeout=5)
    return [dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            for block in result.stdout.strip().split('\n\n')]


def release_report(runtime, manifest_path):
    receipt = json.loads((runtime / 'installed-release.json').read_text())
    recovery = Path(receipt['recovery'])
    result = {k: receipt.get(k) for k in ('revision', 'installed_at', 'deployment_plan',
              'database_backup_created', 'recovery', 'previous_runtime')}
    def recovery_metadata():
        verified = json.loads((recovery / 'backup-verified.json').read_text())
        artifacts = json.loads((recovery / 'artifact-manifest.json').read_text())
        return {'recorded_verified': verified.get('verified'),
                'artifact_count': len(artifacts),
                'database_bytes': {p.name: p.stat().st_size for p in recovery.glob('*.db')},
                'note': 'Recorded verification and file presence; no repeat integrity scan'}
    result['recovery_metadata'] = capture(recovery_metadata)
    def identity():
        manifest = json.loads(manifest_path.read_text())
        names = sorted(name for name in manifest['files'] if
            name.startswith(('worker/src/', 'worker/migrations/', 'lib/')) or
            name in ('deploy/install-reviewed-release.py', '.next/BUILD_ID'))
        if not names or manifest['revision'] != receipt['revision']:
            raise ValueError('Manifest revision or file selection mismatch')
        mismatches = []
        for name in names:
            path = runtime / name
            if not path.resolve().is_relative_to(runtime.resolve()):
                raise ValueError('Manifest path escapes runtime')
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest['files'][name]:
                    mismatches.append(name)
        return {'checked_files': len(names), 'mismatches': mismatches,
                'scope': 'worker source, migration SQL, lib source, installer, build ID; not all build artifacts'}
    result['artifact_identity'] = capture(identity)
    return result


def inspect_database(path):
    # mode=ro prevents creation/updates, query_only adds defense in depth. A
    # progress handler bounds scans; timeout bounds SQLite lock acquisition.
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        def query(sql):
            deadline = time.monotonic() + 3
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            return [dict(row) for row in db.execute(sql).fetchall()]
        queries = {
            'schema': 'SELECT version FROM schema_migrations ORDER BY version',
            'stock_reconciliation': 'SELECT captured_at,status FROM broker_reconciliations ORDER BY captured_at DESC LIMIT 1',
            'stock_lots': 'SELECT status,COUNT(*) AS count FROM paper_trade_lots GROUP BY status',
            'bitcoin_allocations': 'SELECT budget,cash,quantity,risk_paused,started_at FROM btc_allocations LIMIT 6',
            'bitcoin_orders': 'SELECT status,COUNT(*) AS count,SUM(CAST(reserved_cash AS REAL)) AS reserved_cash FROM btc_orders GROUP BY status',
            'bitcoin_qualification': 'SELECT status,COUNT(*) AS count FROM btc_qualifications GROUP BY status',
            'authorizations': 'SELECT status,COUNT(*) AS count FROM paper_authorizations GROUP BY status',
            'policy': 'SELECT id,enabled,discovery_enabled,threshold,pool,sleeve,entry_cap FROM research_policies ORDER BY id DESC LIMIT 1',
            'health': 'SELECT key,at,error IS NOT NULL AS has_error FROM btc_health ORDER BY at DESC LIMIT 20',
            'research': 'SELECT asset,status,error IS NOT NULL AS has_error,COUNT(*) AS count FROM discovery_trials GROUP BY asset,status,has_error',
            'recent_trial_results': "SELECT asset,status,json_extract(result_json,'$.passed') AS passed,json_extract(result_json,'$.scenario_pass_rate') AS scenario_pass_rate,json_extract(result_json,'$.unique_trades') AS unique_trades FROM discovery_trials ORDER BY created_at DESC LIMIT 12",
            'stock_input_presence': """SELECT
                EXISTS(SELECT 1 FROM universe_snapshots) AS universe_present,
                EXISTS(SELECT 1 FROM market_sessions) AS calendar_present,
                EXISTS(SELECT 1 FROM instrument_context WHERE sector IS NOT NULL AND sector!='') AS sectors_present,
                EXISTS(SELECT 1 FROM market_bars WHERE timeframe='1Day' AND adjustment='raw') AS raw_daily_bars_present,
                EXISTS(SELECT 1 FROM market_bars WHERE timeframe='1Day' AND adjustment='all') AS adjusted_daily_bars_present,
                EXISTS(SELECT 1 FROM market_bars b JOIN market_sessions s ON s.trading_date=substr(b.timestamp,1,10)
                    JOIN instrument_context c ON c.instrument_id=b.instrument_id
                    JOIN universe_memberships u ON u.instrument_id=b.instrument_id
                    WHERE u.snapshot_id=(SELECT MAX(id) FROM universe_snapshots)
                    AND b.timeframe='1Day' AND b.adjustment='raw' AND c.sector IS NOT NULL AND c.sector!='') AS exportable_rows_present""",
        }
        return {name: capture(lambda sql=sql: query(sql)) for name, sql in queries.items()}


def broker_observation(path, bitcoin, identities=None):
    prefix = 'BITCOIN_ALPACA' if bitcoin else 'ALPACA'
    key, secret = os.environ.get(prefix + '_API_KEY_ID'), os.environ.get(prefix + '_API_SECRET_KEY')
    if not key or not secret:
        return {'configured': False}
    headers = {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret}
    def get(route):
        status, result = get_json('https://paper-api.alpaca.markets/v2/' + route, headers)
        if status != 200:
            raise ValueError('Paper broker GET failed')
        return result
    account, positions, orders = get('account'), get('positions'), get('orders?status=open&limit=500')
    if identities is not None and account.get('id'):
        identities[bitcoin] = account['id']
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        deadline = time.monotonic() + 3
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        stored = db.execute('SELECT id FROM btc_accounts LIMIT 1' if bitcoin else
            'SELECT account_id FROM broker_account_snapshots ORDER BY captured_at DESC LIMIT 1').fetchone()
    return {'configured': True, 'currency': account.get('currency'), 'cash': account.get('cash'),
            'position_count': len(positions), 'open_order_count_up_to_500': len(orders),
            'local_account_registered': stored is not None,
            'account_identity_matches': stored[0] == account.get('id') if stored else None,
            'distinct_from_stock_key': key != os.environ.get('ALPACA_API_KEY_ID') if bitcoin else None,
            'note': 'Sequential read-only broker observations; not a fill/fee reconciliation or authorization'}


def broker_report(path):
    identities = {}
    results = {asset: capture(lambda btc=btc: broker_observation(path, btc, identities))
               for asset, btc in (('stocks', False), ('bitcoin', True))}
    results['distinct_broker_accounts'] = (
        identities[False] != identities[True] if len(identities) == 2 else None)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('/var/lib/stock-watch/stock-watch.db'))
    parser.add_argument('--runtime', type=Path, default=Path('/opt/stock-watch'))
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--broker-readonly', action='store_true')
    args = parser.parse_args()
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'host': socket.gethostname(),
              'release': capture(lambda: release_report(args.runtime, args.manifest)),
              'services': capture(services), 'availability': capture(availability), 'readiness': capture(readiness),
              'database': capture(lambda: inspect_database(args.database))}
    if args.broker_readonly:
        report['broker'] = broker_report(args.database)
    else:
        report['broker'] = {'available': False, 'reason': 'GET-only broker inspection not requested'}
    print(json.dumps(report, indent=2))
    # No global green flag: HTTP availability, prerequisite readiness, identity,
    # and reconciliation are distinct evidence, not interchangeable proofs.


if __name__ == '__main__':
    main()
