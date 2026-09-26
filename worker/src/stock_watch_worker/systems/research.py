"""Immutable research registry and bounded, cancelable job runner."""
from .automation_config import load_config
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import calendar
import hashlib
import json
import uuid

from .engine import SystemConfig, canonical, digest, instant, replay, validate_dataset


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def audit(db, action, entity, payload):
    db.execute('INSERT INTO system_audit(at,action,entity_id,payload_json) VALUES (?,?,?,?)',
               (now_iso(), action, entity, canonical(payload)))


def register_version(db, config, hypothesis=''):
    identifier = config.sha256
    with db:
        db.execute('INSERT OR IGNORE INTO system_versions VALUES (?,?,?,?,?,?,?)',
                   (identifier, config.asset, config.template, canonical(asdict(config)), config.sha256, now_iso(), hypothesis))
        audit(db, 'version_registered', identifier, {'hypothesis': hypothesis})
    return identifier


def register_dataset(db, path, storage):
    raw = Path(path).read_bytes()
    if len(raw) > 256 * 1024 * 1024:
        raise ValueError('Dataset exceeds the 256 MB import limit')
    data = json.loads(raw)
    validate_dataset(data, data.get('asset'))
    raw = canonical(data).encode()
    sha = hashlib.sha256(raw).hexdigest()
    destination = Path(storage).resolve() / f'{sha}.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != raw:
        raise ValueError('Content-addressed dataset was modified')
    if not destination.exists():
        with destination.open('xb') as stream:
            stream.write(raw)
    with db:
        db.execute('INSERT OR IGNORE INTO system_datasets VALUES (?,?,?,?,?,?)',
                   (sha, data['asset'], str(destination), sha, canonical(data['manifest']), now_iso()))
        audit(db, 'dataset_imported', sha, {'manifest': data['manifest']})
    return sha


def add_months(at, months):
    date = instant(at)
    offset = date.year * 12 + date.month - 1 + months
    year, month = divmod(offset, 12)
    month += 1
    return date.replace(year=year, month=month, day=min(date.day, calendar.monthrange(year, month)[1])).isoformat()


def evaluate(config, data, canceled=lambda: False, progress=lambda value: None):
    # Defaults are frozen. No parameter search uses test or holdout results.
    first, last = data['bars'][0]['at'], data['bars'][-1]['at']
    holdout = add_months(last, -6)
    folds, origin = [], first
    while instant(add_months(origin, 33)) <= instant(holdout):
        validation = add_months(origin, 24)
        test, end = add_months(origin, 30), add_months(origin, 33)
        training_data = {**data, 'bars': [r for r in data['bars'] if instant(r['at']) >= instant(origin)]}
        folds.append({'train_start': origin, 'validation_start': validation, 'test_start': test, 'test_end': end,
                      'validation': replay(config, training_data, start=validation, end=test, canceled=canceled),
                      'test': replay(config, training_data, start=test, end=end, canceled=canceled)})
        progress(min(75,10+len(folds)*5))
        origin = add_months(origin, 3)
    full = replay(config, data, end=holdout if folds else None, canceled=canceled)
    progress(80)
    stress = replay(config, data, cost_multiplier=2, end=holdout if folds else None, canceled=canceled)
    progress(95)
    benchmarks = {}
    for name, bars in data.get('benchmarks', {}).items():
        usable = [b for b in bars if not folds or instant(b['at']) < instant(holdout)]
        if len(usable) > 1:
            benchmarks[name] = positive_return(usable)
    if config.asset == 'bitcoin':
        usable = [b for b in data['bars'] if not folds or instant(b['at']) < instant(holdout)]
        benchmarks['BTC buy and hold (before costs)'] = positive_return(usable)
    benchmarks['Cash'] = 0
    out_of_sample = {'status':'insufficient_history','fold_count':len(folds)}
    if folds:
        capital,peak,drawdown=300.,300.,0.
        trade_count=0
        for fold in folds:
            test=fold['test']
            for point in test['equity_curve']:
                value=capital*point['equity']/300
                peak=max(peak,value)
                drawdown=min(drawdown,value/peak-1)
            capital*=1+test['net_return']
            trade_count+=test['closed_trades']
        out_of_sample.update({'status':'review_required','net_return':capital/300-1,'maximum_drawdown':drawdown,
                              'closed_trades':trade_count,'capital_policy':'Each fold starts flat; normalized returns are chained, not one continuous live portfolio'})
        if trade_count<30: out_of_sample['sample_warning']='Fewer than 30 closed out-of-sample trades'
    return {'out_of_sample':out_of_sample,'base': full, 'double_cost': stress, 'folds': folds, 'benchmarks': benchmarks,
            'holdout_start': holdout if folds else None, 'holdout_status': 'sealed' if folds else 'insufficient_history',
            'coverage': {'first': first, 'last': last, 'bars': len(data['bars'])},
            'selection': 'Frozen defaults; no optimization', 'trial_count': 1,
            'promotion_ready': False,
            'review_note': 'Historical results require forward observation and explicit review. No automatic promotion.'}


def positive_return(bars):
    from .engine import positive
    key='total_return_index' if all(b.get('total_return_index') is not None for b in bars) else 'close'
    return positive(bars[-1][key], 'benchmark close') / positive(bars[0][key], 'benchmark close') - 1


def run_next(db):
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM system_runs WHERE status='running'").fetchone():
            return None
        row = db.execute("SELECT * FROM system_runs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
        if not row:
            return None
        identifier = row['id']
        db.execute("UPDATE system_runs SET status='running',started_at=?,progress=5 WHERE id=?", (now_iso(),identifier))
    try:
        version = db.execute('SELECT * FROM system_versions WHERE id=?', (row['version_id'],)).fetchone()
        dataset = db.execute('SELECT * FROM system_datasets WHERE id=?', (row['dataset_id'],)).fetchone()
        config = load_config(json.loads(version['config_json']))
        if config.sha256 != version['config_sha256']:
            raise ValueError('Strategy hash mismatch')
        raw = Path(dataset['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != dataset['sha256']:
            raise ValueError('Dataset hash mismatch')
        data = json.loads(raw)
        def canceled():
            return bool(db.execute('SELECT cancel_requested FROM system_runs WHERE id=?', (identifier,)).fetchone()[0])
        def progress(value):
            from .workspace import stage
            stage(db,identifier,f'Replaying validation, test and cost scenarios ({value}%)')
            with db: db.execute('UPDATE system_runs SET progress=? WHERE id=?',(value,identifier))
        result = evaluate(config, data, canceled, progress)
        from .reporting import enrich
        enrich(result, config.asset)
        result.update({'dataset_sha256': dataset['sha256'], 'config_sha256': config.sha256})
        result['trial_count']=db.execute('SELECT COUNT(*) FROM system_runs WHERE dataset_id=?',(dataset['id'],)).fetchone()[0]
        result['distinct_versions_tested']=db.execute('SELECT COUNT(DISTINCT version_id) FROM system_runs WHERE dataset_id=?',(dataset['id'],)).fetchone()[0]
        # Preserve full evidence on disk; keep operational rows and dashboard reads small.
        artifact_raw=canonical(result).encode()
        artifact=Path(dataset['path']).parent / f'{identifier}.result.json'
        with artifact.open('xb') as stream: stream.write(artifact_raw)
        result['result_artifact_sha256']=hashlib.sha256(artifact_raw).hexdigest()
        def compact(report):
            curve=report.get('equity_curve',[])
            stride=max(1,(len(curve)+499)//500)
            report['equity_curve']=curve[::stride]+([curve[-1]] if curve and (len(curve)-1)%stride else [])
            report['fills_in_full_artifact']=len(report.get('fills',[]))
            report['fills']=report.get('fills',[])[-100:]
            if report.get('metrics'):
                report['metrics']['trades_in_full_artifact']=len(report['metrics'].get('trades',[]))
                report['metrics']['trades']=report['metrics'].get('trades',[])[-100:]
        compact(result['base']); compact(result['double_cost'])
        for fold in result['folds']:
            compact(fold['test']); compact(fold['validation'])
        with db:
            db.execute("UPDATE system_runs SET status='succeeded',progress=100,finished_at=?,result_json=? WHERE id=?",
                       (now_iso(), canonical(result), identifier))
            audit(db, 'backtest_completed', identifier, {'dataset': dataset['id'], 'version': version['id']})
    except Exception as error:
        with db:
            db.execute('UPDATE system_runs SET status=?,finished_at=?,error=? WHERE id=?',
                       ('canceled' if isinstance(error, InterruptedError) else 'failed', now_iso(), str(error)[:1000],identifier))
    return identifier
