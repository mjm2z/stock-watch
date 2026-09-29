"""Research-only snapshots and paired experiments. No broker or enrollment imports."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import math
from .engine import canonical, digest, instant, replay, validate_dataset
from .automation_config import load_config, BitcoinConfig
from .research import now_iso, evaluate
from .rules import operand, evaluate_group
from .timeframes import advance
from .reporting import trade_metrics


def engine_identity():
    names = ('engine.py', 'rules.py', 'timeframes.py', 'reporting.py', 'research.py', 'inspection.py')
    return digest({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names})


def inspect_rules(config, history):
    def group_state(group):
        return {'op': group['op'], 'state': evaluate_group(group, history), 'conditions': [
            group_state(row) if row['op'] in ('all', 'any') else {
                'op': row['op'], 'left': row['left'], 'right': row['right'],
                'left_value': operand(row['left'], history), 'right_value': operand(row['right'], history),
                'state': evaluate_group({'op': 'all', 'conditions': [row]}, history),
            } for row in group['conditions']]}
    return {'entry': group_state(config.entry_rules), 'exit': group_state(config.exit_rules)} if getattr(config, 'protocol', None) == 'visual-rules-v1' else {}


def execute_preview(db, job, database):
    body = json.loads(job['payload_json'])
    snapshot = db.execute('SELECT * FROM research_snapshots WHERE id=?', (body['snapshot'],)).fetchone()
    if not snapshot or snapshot['asset'] != body['asset']:
        raise ValueError('Research snapshot unavailable')
    config = load_config(json.loads(snapshot['config_json']))
    dataset = db.execute('SELECT * FROM system_datasets WHERE id=? AND asset=?', (body['dataset'], body['asset'])).fetchone()
    if not dataset:
        raise ValueError('Retained dataset unavailable')
    path = Path(dataset['path'])
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Retained dataset exceeds preview resource bound')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != dataset['sha256']:
        raise ValueError('Retained dataset hash mismatch')
    data = json.loads(raw)
    validate_dataset(data, config.asset)
    if len(data['bars']) > 60000:
        raise ValueError('Preview exceeds 60,000 bars; prepare a smaller dataset')
    frame = getattr(config, 'timeframe', '1Day' if config.asset == 'stocks' else '1Hour')
    actual_frame = data['manifest'].get('timeframe', '1Day' if config.asset == 'stocks' else None)
    if actual_frame != frame:
        raise ValueError('Dataset decision timeframe does not match the snapshot; no fabricated resampling')
    start, end = instant(body['start']), instant(body['end'])
    scored = [r for r in data['bars'] if start <= instant(r['at']) < end]
    if not scored:
        raise ValueError('No completed bars in the selected scoring interval')
    def canceled():
        return bool(db.execute('SELECT cancel_requested FROM workspace_jobs WHERE id=?', (job['id'],)).fetchone()[0])
    if canceled():
        raise InterruptedError('Preview canceled')
    identity = digest({**body, 'dataset_sha256': dataset['sha256'], 'engine': engine_identity(), 'config': config.sha256})
    cached = db.execute("SELECT p.id,p.result_json FROM research_previews p JOIN workspace_jobs j ON j.id=p.id WHERE p.identity=? AND j.status='succeeded' AND p.result_json IS NOT NULL ORDER BY p.created_at LIMIT 1", (identity,)).fetchone()
    # Even a cached inspection exposes an interval. Conservative asset-wide scope
    # intentionally catches copied/revised configurations whose lineage is unknown.
    inspected = db.execute('SELECT COUNT(*) FROM research_access WHERE asset=? AND starts_at<? AND ends_at>?',
                           (body['asset'], body['end'], body['start'])).fetchone()[0]
    with db:
        db.execute('INSERT INTO research_access(asset,snapshot_id,dataset_id,starts_at,ends_at,purpose,at) VALUES (?,?,?,?,?,?,?)',
                   (body['asset'], snapshot['id'], dataset['id'], body['start'], body['end'], 'exploratory inspection; not untouched holdout', now_iso()))
    if cached:
        result = json.loads(cached['result_json'])
        result = {**result, 'reused_from': cached['id'], 'independent_evidence': False, 'prior_interval_inspections': inspected}
    else:
        preflight = {
            'basic_inputs': 'available', 'indicator_warmup': 'Per-symbol values below; unavailable rules never become false',
            'scored_coverage': {'requested_start': body['start'], 'requested_end': body['end'], 'first': scored[0]['at'], 'last': scored[-1]['at'], 'bars': len(scored)},
            'data_treatment': data['manifest'], 'execution_authority': 'research-only; no qualification or promotion',
            'holdout': 'Every displayed interval is exploratory for subsequent related selection',
        }
        result = {'snapshot': snapshot['id'], 'config_hash': config.sha256, 'engine_hash': engine_identity(),
                  'dataset': dataset['id'], 'dataset_hash': dataset['sha256'], 'configuration': asdict(config),
                  'identity': identity, 'authority': 'research-only', 'evidence_class': 'demonstration fixture' if data['manifest'].get('demonstration') else 'historical simulation',
                  'base_currency': 'USD', 'capital': 1000, 'preflight': preflight,
                  'created_at': now_iso(), 'prior_interval_inspections': inspected,
                  'inspection': [],
                  'inspection_note': 'Simulated rules on the latest retained completed bars, not live signals',
                  'comparison_key': digest({k: body[k] for k in ('asset','dataset','start','end','costMultiplier','startingCash')}),
                  'limitations': ['No order authority', 'Between-observation drawdowns may be missed', 'DSR/PBO and calibrated probabilities unavailable; complete selection inputs absent', 'Legacy search history unknown']}
        inspected_rules = {}
        def inspect_decision(symbol, history, action, reason):
            # The callback receives the exact replay history after splits, gap resets
            # and completed-bar timing. There is no second indicator implementation.
            if symbol not in inspected_rules and len(inspected_rules) >= 50:
                return
            next_at = advance(instant(history[-1]['at']), frame).isoformat() if config.asset == 'bitcoin' else None
            if config.asset == 'stocks':
                session = db.execute('SELECT closes_at FROM market_sessions WHERE closes_at>? ORDER BY closes_at LIMIT 1', (history[-1]['at'],)).fetchone()
                next_at = session[0] if session else None
            inspected_rules[symbol] = {'symbol':symbol, 'completed_bar':history[-1]['at'],
                'next_bar_boundary':next_at, 'available_bars':len(history), 'decision':action, 'reason':reason,
                **inspect_rules(config, history)}
        continuous = replay(config, data, start=body['start'], end=body['end'], starting_cash=1000,
                            cost_multiplier=body['costMultiplier'], canceled=canceled, inspect_decision=inspect_decision)
        result['inspection'] = list(inspected_rules.values())
        if not body.get('inspectOnly'):
            continuous['metrics'] = trade_metrics(continuous, config.asset)
            peak = 1000.
            for point in continuous['equity_curve']:
                peak = max(peak, point['equity'])
                point['drawdown'] = 100 * (point['equity'] / peak - 1)
                point['net_percent'] = 100 * (point['equity'] / 1000 - 1)
            result['continuous'] = continuous
            selected_data = {**data, 'bars': scored}
            # Existing chronological fold protocol is reported separately, not mixed
            # into this experiment's $1,000 continuous-account outcome.
            formal = evaluate(config, selected_data, canceled=canceled)
            result['fold_analysis'] = {'out_of_sample': formal['out_of_sample'], 'coverage': formal['coverage'],
                                       'holdout_status': 'exploratory after this inspection', 'fold_count': len(formal['folds']),
                                       'capital_note': 'Existing protocol: flat-start $300 folds; separate from $1,000 continuous replay'}
            result['preflight']['fold_feasibility'] = formal['out_of_sample']['status']
            result['benchmarks'] = {'cash_price_return': 0, 'funding_matched_SPY': {'available': False, 'reason': 'Matching funded valuations and dividend treatment required'}}
        else:
            result['preflight']['fold_feasibility'] = 'Not run during visual inspection'
    if canceled():
        raise InterruptedError('Preview canceled')
    if not cached:
        # Full evidence remains in content-addressed storage; the application DB
        # holds bounded display series only. Metrics were computed before sampling.
        raw_result = canonical(result).encode()
        artifact_hash = hashlib.sha256(raw_result).hexdigest()
        storage = Path(str(database)+'.systems-data')
        storage.mkdir(parents=True, exist_ok=True)
        artifact = storage / (artifact_hash+'.preview.json')
        if artifact.exists() and artifact.read_bytes() != raw_result:
            raise ValueError('Research artifact was modified')
        if not artifact.exists():
            with artifact.open('xb') as stream:
                stream.write(raw_result)
        result['artifact_sha256'] = artifact_hash
        for section in ('continuous',):
            if section in result:
                report = result[section]
                curve = report.get('equity_curve', [])
                if len(curve)>600:
                    report['equity_curve'] = [curve[int(i*(len(curve)-1)/599)] for i in range(600)]
                fills = report.get('fills', [])
                report['fills_in_full_artifact'] = len(fills)
                report['fills'] = fills[:200]
                if 'metrics' in report:
                    report['metrics']['trades_in_full_artifact'] = len(report['metrics'].get('trades', []))
                    report['metrics']['trades'] = report['metrics'].get('trades', [])[:200]
    with db:
        db.execute('UPDATE research_previews SET dataset_id=?,identity=?,result_json=? WHERE id=?',
                   (dataset['id'], identity, canonical(result), job['id']))
        if cached:
            db.execute('UPDATE research_attempts SET reused_from=? WHERE id=?', (cached['id'], job['id']))
    return {'preview': job['id'], 'snapshot': snapshot['id'], 'authority': 'research-only', 'reused_from': cached['id'] if cached else None}


def execute_demo(db, job, database):
    """Deterministic teaching data, stored with explicit fixture provenance."""
    from .datasets import save_dataset
    at = now_iso()
    baseline = BitcoinConfig(asset='bitcoin', template='breakout', timeframe='1Day', entry=55, exit=20)
    candidate = BitcoinConfig(**{**asdict(baseline), 'exit': 10})
    rows = []
    first = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for i in range(730):
        price = 100 + i * .08 + 12 * math.sin(i / 22) + 3 * math.sin(i / 5)
        timestamp = first + timedelta(days=i)
        rows.append({'symbol': 'BTC/USD', 'at': timestamp.isoformat(), 'available_at': timestamp.isoformat(),
                     'open': price, 'high': price+1, 'low': price-1, 'close': price, 'volume': 100,
                     'quote': {'at': (timestamp+timedelta(seconds=1)).isoformat(), 'bid': price, 'ask': price, 'synthetic': True}})
    data = {'schema_version': 1, 'asset': 'bitcoin', 'bars': rows,
            'manifest': {'provider': 'deterministic demonstration fixture', 'venue': 'simulated; not market observations', 'timeframe': '1Day',
                         'fidelity': 'bar_approximation', 'demonstration': True, 'actual_start': rows[0]['at'], 'actual_end': rows[-1]['at']}}
    dataset = save_dataset(db, data, Path(str(database)+'.systems-data'))
    snapshots = []
    with db:
        for role, config in [('baseline',baseline),('candidate',candidate)]:
            sid = digest({'asset': 'bitcoin', 'config': asdict(config)})
            db.execute('INSERT OR IGNORE INTO research_snapshots(id,asset,config_json,name,created_at) VALUES (?,?,?,?,?)',
                       (sid,'bitcoin',canonical(asdict(config)),f'DEMO breakout 55/{config.exit}',at))
            snapshots.append(sid)
        plan = {'hypothesis': 'A shorter exit lookback may reduce drawdown at the cost of turnover',
                'mechanism': 'Only breakout exit changes from 20 to 10 completed daily bars',
                'primaryOutcome': 'Net return after identical modeled costs', 'riskConstraint': 'Candidate maximum drawdown no worse than baseline',
                'selectionRule': 'Historically promising only if net return improves and drawdown does not worsen; fewer than 30 closed trades is inconclusive',
                'reviewPoint': 'Review this single paired replay; do not optimize the fixture',
                'baseline': snapshots[0], 'candidate': snapshots[1], 'dataset': dataset,
                'start': rows[100]['at'], 'end': (first+timedelta(days=730)).isoformat(),
                'costMultiplier': 1, 'startingCash': 1000, 'authority': 'research-only', 'demonstration': True,
                'real_data_plan': 'Blocked until retained daily BTC data, coverage and matching costs pass preflight. Fixture outcomes are not investment evidence.'}
        db.execute('INSERT OR IGNORE INTO research_experiments VALUES (?,?,?,?,?)', (job['id'],'bitcoin',None,canonical(plan),at))
        for role,sid in zip(('baseline','candidate'), snapshots):
            identity = job['id']+'-'+role
            payload = {'asset':'bitcoin','snapshot':sid,'dataset':dataset,'start':plan['start'],'end':plan['end'],'costMultiplier':1,'startingCash':1000,'inspectOnly':False}
            db.execute('INSERT OR IGNORE INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,?,?,?)', (identity,'preview',canonical(payload),at))
            db.execute('INSERT OR IGNORE INTO research_previews(id,snapshot_id,created_at) VALUES (?,?,?)',(identity,sid,at))
            db.execute('INSERT OR IGNORE INTO research_attempts VALUES (?,?,?,?,?,?)',(identity,job['id'],sid,role,None,at))
    return {'experiment':job['id'],'evidence':'demonstration fixture','authority':'research-only'}
