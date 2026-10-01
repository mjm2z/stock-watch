#!/usr/bin/env python3
"""Install a prebuilt release on the authoritative host with retained recovery data."""
from datetime import datetime
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo


def run(*args):
    return subprocess.run(args, check=True, text=True)


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def drain_services(unit_lines, current_pid=None):
    # A supervised installer is not a writer that it can wait to drain.
    current_pid = str(os.getpid() if current_pid is None else current_pid)
    services = []
    for line in unit_lines:
        name = line.split()[0]
        if not name.endswith('.service') or name == 'stock-watch-web.service':
            continue
        if output('systemctl', 'show', '-p', 'MainPID', '--value', name) == current_pid:
            continue
        services.append(name)
    return services


def other_release_owners(unit_lines, current_pid=None):
    """Also recognize older installers that predate the process lock."""
    current_pid = str(os.getpid() if current_pid is None else current_pid)
    return [line.split()[0] for line in unit_lines if line.strip()
            and line.split()[0].startswith('stock-watch-release-')
            and output('systemctl', 'show', '-p', 'MainPID', '--value', line.split()[0]) != current_pid]


def counts(db):
    names = ('paper_orders', 'paper_exit_orders', 'paper_trade_lots', 'signals',
             'strategy_versions', 'scan_runs', 'system_deployments', 'system_orders',
             'system_runs', 'research_notes', 'research_watchlist', 'btc_orders',
             'btc_allocations', 'btc_accounts', 'btc_enrollments')
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {n: db.execute('SELECT COUNT(*) FROM "' + n + '"').fetchone()[0]
            for n in names if n in existing}


# Quiescent migration invariants, not post-resumption trading snapshots. Keep
# observed health/research activity out of this list; preserve actual authority,
# immutable definitions, and all owned cash/share/fill/reservation records.
PRESERVED_TABLES = (
    'strategy_versions', 'system_versions', 'system_deployments',
    'system_stock_control', 'system_orders', 'paper_orders', 'paper_fills',
    'paper_trade_lots', 'paper_exit_orders', 'paper_exit_fills',
    'paper_exit_timing_policies', 'btc_accounts', 'btc_allocations',
    'btc_enrollments', 'btc_orders', 'btc_fills', 'btc_fees',
    'btc_fee_allocations', 'btc_qualifications', 'btc_evaluations',
    'paper_authorizations', 'research_policies', 'paper_cashflows', 'system_entry_controls',
)


def authority(db, baseline=None):
    """Snapshot trading authority and ownership, allowing only additive schema changes."""
    existing={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result={}
    for name in PRESERVED_TABLES:
        if name not in existing:continue
        columns=baseline[name]['columns'] if baseline and name in baseline else [r[1] for r in db.execute('PRAGMA table_info("'+name+'")')]
        rows=db.execute('SELECT '+','.join('"'+c+'"' for c in columns)+' FROM "'+name+'"').fetchall()
        result[name]={'columns':columns,'rows':sorted(json.dumps(tuple(row),sort_keys=True) for row in rows)}
    return result


def verify_files(source, manifest):
    def verify(item):
        name, expected = item
        path = source / name
        if not path.resolve().is_relative_to(source):
            raise RuntimeError('Unsafe release manifest path')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise RuntimeError('Staged release changed: ' + name)
    entries = iter(manifest['files'].items())
    verified = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        while batch := list(islice(entries, 128)):
            list(pool.map(verify, batch))
            verified += len(batch)
            if verified % 4096 == 0:
                print('Verified files:', verified, flush=True)


def verify_environment_files(source, manifest):
    for path in source.glob('.env*'):
        # Only the checksum-verified, tracked example is a release artifact.
        if (path.name != '.env.example' or path.is_symlink() or not path.is_file()
                or path.name not in manifest['files']):
            raise RuntimeError('Release staging contains an unapproved environment file: ' + path.name)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest['files'][path.name]:
                raise RuntimeError('Environment example differs from reviewed source')


def deployment_plan(source, runtime, database, force_backup=False):
    """Require exact migration history for code-only deployment; never hide drift."""
    staged = {p.stem: p.read_bytes() for p in (source / 'worker/migrations').glob('*.sql')}
    installed = {p.stem: p.read_bytes() for p in (runtime / 'worker/migrations').glob('*.sql')}
    if not staged or not installed:
        raise RuntimeError('Cannot establish installed migration history')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        applied = {row[0] for row in db.execute('SELECT version FROM schema_migrations')}
    for version in applied:
        if version not in staged or version not in installed or staged[version] != installed[version]:
            raise RuntimeError('Applied migration removed or changed: ' + version)
    pending = sorted(set(staged) - applied)
    # Initialization changes can alter seeded data without adding SQL. Treat these
    # conservatively; code-only installs never run init or seeding.
    initialization_changed = any(
        not (runtime / name).is_file() or (source / name).read_bytes() != (runtime / name).read_bytes()
        for name in ('worker/src/stock_watch_worker/database.py',
                     'worker/src/stock_watch_worker/systems/cli.py'))
    full = bool(force_backup or pending or initialization_changed)
    return {'mode': 'database' if full else 'code-only', 'pending_migrations': pending,
            'initialization_changed': initialization_changed, 'forced_backup': force_backup}



def recovery_inputs(database):
    databases = [database]
    history = database.with_name(database.name + '.bitcoin-history.db')
    if history.exists(): databases.append(history)
    for name in ('manual-paper.db','market-data.db'):
        auxiliary=database.with_name(name)
        if auxiliary.exists(): databases.append(auxiliary)
    return databases, [p for p in database.parent.iterdir() if p.is_dir()]


def artifact_files(database, recovery=None):
    databases, _ = recovery_inputs(database)
    excluded = {str(p) + suffix for p in databases for suffix in ('', '-wal', '-shm', '-journal')}
    for path in database.parent.rglob('*'):
        if recovery and (path == recovery or path.is_relative_to(recovery)):
            continue
        if path.is_symlink():
            raise RuntimeError('Review artifact symlink before migration: ' + str(path))
        if path.is_file() and str(path) not in excluded:
            yield path


def verify_artifact_locations(database):
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='system_datasets'").fetchone(): return
        for identifier, value in db.execute('SELECT id,path FROM system_datasets'):
            path = Path(value)
            if not path.is_absolute() or not path.resolve().is_relative_to(database.parent.resolve()) or not path.is_file():
                raise RuntimeError('Dataset requires reviewed recovery mapping before migration: ' + str(identifier))
        for identifier, value, result in db.execute("SELECT r.id,d.path,r.result_json FROM system_runs r JOIN system_datasets d ON d.id=r.dataset_id WHERE r.result_json IS NOT NULL"):
            expected = json.loads(result).get('result_artifact_sha256')
            if expected:
                path = Path(value).parent / (identifier + '.result.json')
                if not path.is_file():
                    raise RuntimeError('Missing retained result artifact: ' + identifier)
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        raise RuntimeError('Retained result artifact hash mismatch: ' + identifier)


def preserve_supporting_evidence(database, recovery):
    verify_artifact_locations(database)
    databases, _ = recovery_inputs(database)
    for path in databases[1:]:
        print('Backing up auxiliary database: ' + path.name, flush=True)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(recovery / path.name)) as backup:
                original.backup(backup, pages=4096)
                if backup.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise RuntimeError('Auxiliary database verification failed')
    manifest = {}
    for path in artifact_files(database, recovery):
        relative = path.relative_to(database.parent)
        destination = recovery / 'artifacts' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        with path.open('rb') as src, destination.open('rb') as dest:
            digest = hashlib.file_digest(src, 'sha256').hexdigest()
            if digest != hashlib.file_digest(dest, 'sha256').hexdigest():
                raise RuntimeError('Artifact recovery verification failed: ' + str(relative))
        manifest[str(relative)] = digest
    (recovery / 'artifact-manifest.json').write_text(json.dumps(manifest, indent=2))


def preserve_database(database, recovery, plan):
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as old:
        before = counts(old)
        authority_before = authority(old)
        if plan['mode'] == 'database':
            print('Creating a fresh recovery database; originals are retained.', flush=True)
            last = [0.0]
            def progress(status, remaining, total):
                if time.monotonic() - last[0] > 10:
                    print(f'Backup copied {total-remaining}/{total} pages...', flush=True)
                    last[0] = time.monotonic()
            with closing(sqlite3.connect(recovery / 'stock-watch.db')) as backup:
                old.backup(backup, pages=4096, progress=progress)
                print('Verifying fresh recovery database...', flush=True)
                if backup.execute('PRAGMA quick_check').fetchall() != [('ok',)] or counts(backup) != before:
                    raise RuntimeError('Backup verification failed; release not installed')
            preserve_supporting_evidence(database, recovery)
            (recovery / 'backup-verified.json').write_text(json.dumps({'counts': before, 'verified': True}))
        else:
            print('Code-only release: database backup and initialization skipped; existing database retained.', flush=True)
    return before, authority_before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true', help='Verify staging without changing files or services')
    parser.add_argument('--full-backup', action='store_true', help='Force a verified database recovery copy, even without pending migrations')
    parser.add_argument('--compact-database', action='store_true', help='Retry offline compaction after migration 023; forces a fresh verified backup')
    args = parser.parse_args()
    if socket.gethostname().split('.')[0] != 'a1347-m' or (os.geteuid() != 0 and not args.check):
        raise SystemExit('Run on a1347-m; installation requires root')
    now = datetime.now(ZoneInfo('America/New_York'))
    if not args.check and now.weekday() < 5 and 570 <= now.hour * 60 + now.minute < 960:
        raise SystemExit('Run outside US market hours')
    source = args.source.resolve()
    if source.parent != Path('/home/mjm2z/stock-watch-releases'):
        raise SystemExit('Unexpected release staging directory')
    manifest = json.loads((source / 'reviewed-release.json').read_text())
    verify_files(source, manifest)
    for required in ('.next/BUILD_ID', 'package-lock.json', 'worker/migrations/020_correctness.sql', '.signal-worker/lib/worker-dashboard.js'):
        if required not in manifest['files']:
            raise RuntimeError('Incomplete reviewed release: ' + required)
    verify_environment_files(source, manifest)
    wheels = list((source / 'release-wheels').glob('stock_watch_worker-*.whl'))
    if len(wheels) != 1:
        raise RuntimeError('Expected one prebuilt worker wheel')
    if args.check:
        print('Release preflight passed; no files or services changed. Revision:', manifest['revision'])
        return
    release_lock = open('/run/stock-watch-reviewed-release.lock', 'a')
    try:
        fcntl.flock(release_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another reviewed installer owns the release; no changes made')
    owners = other_release_owners(output('systemctl', 'list-units', '--type=service',
        '--state=running,activating', '--no-legend', '--plain', 'stock-watch-release-*').splitlines())
    if owners:
        raise SystemExit('Existing release owner must finish first: ' + ', '.join(owners))
    runtime = Path('/opt/stock-watch')
    database = Path('/var/lib/stock-watch/stock-watch.db')
    plan = deployment_plan(source, runtime, database, args.full_backup or args.compact_database)
    if '023_company_fact_storage' in plan['pending_migrations']:
        raise SystemExit('Complete and verify staged storage release fb6c33a before installing this UI release; no services changed')
    print('Deployment plan: ' + json.dumps(plan), flush=True)
    stamp = datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
    recovery = Path('/var/backups/stock-watch-releases') / stamp
    databases, artifact_directories = recovery_inputs(database)
    backup_bytes = (sum(p.stat().st_size for p in databases) +
                    sum(p.stat().st_size for p in artifact_files(database))) if plan['mode'] == 'database' else 0
    needs_compaction = args.compact_database or '023_company_fact_storage' in plan['pending_migrations']
    reserve = max(20 * 1024**3, database.stat().st_size * 2 + 5 * 1024**3) if needs_compaction else 20 * 1024**3
    if shutil.disk_usage('/').free < backup_bytes + reserve:
        raise RuntimeError('Insufficient room for fresh backup and reserve')
    if plan['mode'] == 'database': verify_artifact_locations(database)
    os.umask(0o077)
    recovery.mkdir(parents=True)
    (recovery / 'deployment-plan.json').write_text(json.dumps(plan, indent=2))
    shutil.copytree('/etc/stock-watch', recovery / 'config')
    units = output('systemctl', 'list-unit-files', 'stock-watch-*', '--no-legend').splitlines()
    timers = [line.split()[0] for line in units if line.split()[0].endswith('.timer')]
    enabled = {unit: output('systemctl', 'is-enabled', unit) for unit in timers
               if subprocess.run(['systemctl', 'is-enabled', '--quiet', unit]).returncode == 0}
    coordinator_enabled = 'stock-watch-bitcoin-automation.timer' in enabled or subprocess.run(['systemctl','is-enabled','--quiet','stock-watch-execution.service']).returncode == 0
    if coordinator_enabled and 'stock-watch-bitcoin-trading.timer' in enabled:
        raise RuntimeError('Competing legacy Bitcoin timer enabled; reconcile ownership before cutover')
    (recovery / 'execution-cutover.json').write_text(json.dumps({'replace_coordinator':coordinator_enabled}))
    (recovery / 'enabled-timers.json').write_text(json.dumps(enabled, indent=2))
    if timers:
        run('systemctl', 'stop', *timers)
    persistent = [line.split()[0] for line in units if line.split()[0] in ('stock-watch-market-data.service','stock-watch-manual-paper.service','stock-watch-execution.service')]
    if persistent: run('systemctl','stop',*persistent)
    services = drain_services(units)
    deadline = time.monotonic() + 600
    while any(output('systemctl', 'show', '-p', 'ActiveState', '--value', s)
              in ('active', 'activating', 'deactivating') for s in services):
        if time.monotonic() > deadline:
            raise RuntimeError('Jobs still active; timers remain stopped. Review before retrying.')
        time.sleep(5)
    run('systemctl', 'stop', 'stock-watch-web.service')
    # Recheck after draining writers, before replacing any runtime files.
    if deployment_plan(source, runtime, database, args.full_backup or args.compact_database) != plan:
        raise RuntimeError('Migration state changed during drain; review before retrying')
    before, authority_before = preserve_database(database, recovery, plan)
    previous = runtime.with_name('stock-watch.before-' + stamp)
    runtime.rename(previous)
    os.umask(0o022)
    runtime.mkdir(mode=0o755)
    # Leave the full previous runtime available; no production artifacts are removed.
    run('rsync', '-a', '--exclude=reviewed-release.json', str(source) + '/', str(runtime) + '/')
    run('chown', '-R', 'root:root', str(runtime))
    run('chmod', '755', str(runtime))
    run('python3.12', '-m', 'venv', str(runtime / '.venv'))
    run(str(runtime / '.venv/bin/pip'), 'install', '--no-index', str(runtime / 'release-wheels' / wheels[0].name))
    run('chown', '-R', 'stock-watch:stock-watch', str(runtime / '.next/cache'))
    env = Path('/etc/stock-watch/systems.env')
    if not env.exists():
        shutil.copyfile(runtime / 'deploy/systems.env.example', env)
        env.chmod(0o600)
    text = env.read_text()
    if 'SYSTEMS_OPERATOR_TOKEN=\n' in text:
        text = text.replace('SYSTEMS_OPERATOR_TOKEN=\n', 'SYSTEMS_OPERATOR_TOKEN=' + secrets.token_urlsafe(48) + '\n')
        env.write_text(text)
    # Migrate storage and seed systems; existing trading authority is verified below.
    if plan['mode'] == 'database':
        run('runuser', '-u', 'stock-watch', '--', str(runtime / '.venv/bin/stock-watch-systems'),
            '--database', str(database), 'init')
    if needs_compaction:
        marker = json.loads((recovery / 'backup-verified.json').read_text())
        if marker.get('verified') is not True:
            raise RuntimeError('Fresh recovery verification is required before compaction')
        print('Deduplication applied. Compacting offline; services remain stopped until verified.', flush=True)
        run('runuser', '-u', 'stock-watch', '--', str(runtime / '.venv/bin/python'),
            str(runtime / 'deploy/compact-database.py'), str(database))
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as current:
        current_counts=counts(current)
        if any(current_counts.get(key)!=value for key,value in before.items()):
            raise RuntimeError('Legacy ledger counts changed during migration; services remain stopped')
        authority_after=authority(current,authority_before)
        if any(authority_after.get(key)!=value for key,value in authority_before.items()):
            raise RuntimeError('Existing trading authority changed during migration; services remain stopped')
    run('bash', str(runtime / 'deploy/install-systems-root.sh'), '--skip-init')
    for name in ('market-data','manual-paper','execution'):
        run('install','-o','root','-g','root','-m','0644',str(runtime / ('deploy/systemd/stock-watch-'+name+'.service')),'/etc/systemd/system/')
    for name in ('stock-watch-storage-cleanup.service', 'stock-watch-storage-cleanup.timer'):
        run('install', '-o', 'root', '-g', 'root', '-m', '0644',
            str(runtime / 'deploy/systemd' / name), '/etc/systemd/system/')
    run('systemctl','daemon-reload')
    run('systemctl', 'enable', '--now', 'stock-watch-storage-cleanup.timer')
    if coordinator_enabled:
        run('systemctl','disable','--now','stock-watch-bitcoin-automation.timer')
        enabled.pop('stock-watch-bitcoin-automation.timer',None)
        run('systemctl','enable','--now','stock-watch-execution.service')
    run('systemctl','enable','--now','stock-watch-market-data.service','stock-watch-manual-paper.service')
    run('systemctl','is-active','--quiet','stock-watch-market-data.service','stock-watch-manual-paper.service')
    if coordinator_enabled: run('systemctl','is-active','--quiet','stock-watch-execution.service')
    for mode in ('enabled', 'enabled-runtime'):
        selected = [unit for unit, state in enabled.items() if state == mode]
        if selected:
            run('systemctl', 'enable', *(['--runtime'] if mode == 'enabled-runtime' else []), '--now', *selected)
    for route in ('/api/health', '/api/systems?asset=stocks', '/api/systems?asset=bitcoin', '/api/bitcoin', '/api/systems/workspace?asset=stocks', '/api/systems/workspace?asset=bitcoin', '/api/systems/control?asset=bitcoin', '/api/systems/activity?asset=bitcoin', '/crypto', '/manual-paper', '/api/health/market-feed', '/favicon.ico'):
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:3001' + route, timeout=10) as response:
                    if response.status == 200:
                        break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Release readiness failed: ' + route)
    receipt = {'revision': manifest['revision'], 'recovery': str(recovery),
               'deployment_plan': plan, 'database_backup_created': plan['mode'] == 'database',
               'bitcoin_execution_owner': 'stock-watch-execution.service' if coordinator_enabled else 'unchanged-disabled',
               'manual_account_configuration': 'requires separately confirmed setup; never inferred from service activation',
               'previous_runtime': str(previous), 'legacy_counts': before,
               'installed_at': datetime.now(ZoneInfo('UTC')).isoformat()}
    (runtime / 'installed-release.json').write_text(json.dumps(receipt, indent=2))
    (runtime / 'installed-release.json').chmod(0o644)
    print('Release verified. Existing timers restored; research/watch-only timers enabled. No strategy activated.')
    print('Recovery directory:', recovery)
    print('Operator token is retained privately in /etc/stock-watch/systems.env')


if __name__ == '__main__':
    main()
