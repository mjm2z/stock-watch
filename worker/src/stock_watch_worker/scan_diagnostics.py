"""Reconciled, descriptive scan funnel; never changes qualification thresholds."""
from collections import Counter
from datetime import datetime, timezone
import json
from .provenance import present, canonical


def diagnostic(db, scan_id):
    scan=db.execute('SELECT * FROM scan_runs WHERE id=?',(scan_id,)).fetchone()
    if not scan:raise ValueError('Unknown scan')
    strategy=db.execute('SELECT config_json FROM strategy_versions WHERE id=?',(scan['strategy_version_id'],)).fetchone()
    config=json.loads(strategy[0]); limits=config['qualification']
    rows=db.execute('SELECT * FROM signals WHERE scan_run_id=?',(scan_id,)).fetchall()
    primary=Counter();secondary=Counter();bands=Counter();horizons=Counter()
    usable=score_qualified=qualified=0
    for row in rows:
        reasons=json.loads(row['reasons_json']);secondary.update(set(reasons))
        horizons[str(row['horizon_trading_days'])]+=1
        bands[str(min(90,int(row['opportunity_score']//10)*10))]+=1
        complete=row['data_completeness']>=limits['minimum_data_completeness']
        scored=row['opportunity_score']>=limits['minimum_score']
        usable+=complete;score_qualified+=complete and scored
        accepted=row['decision']=='qualified';qualified+=accepted
        reason='qualified' if accepted else 'insufficient_coverage' if not complete else 'score_below_threshold' if not scored else 'risk_not_allowed' if row['risk_level'] not in limits['allowed_risk_levels'] else reasons[0] if reasons else row['decision']
        primary[reason]+=1
    orders=db.execute('''SELECT o.*, (SELECT decision FROM entry_checks e WHERE e.order_id=o.id ORDER BY checked_at DESC,id DESC LIMIT 1) AS entry_decision,
        EXISTS(SELECT 1 FROM paper_fills f WHERE f.order_id=o.id) AS has_fill
        FROM paper_orders o JOIN signals s ON s.id=o.signal_id WHERE s.scan_run_id=?''',(scan_id,)).fetchall()
    metrics=json.loads(scan['metrics_json'] or '{}')
    instruments=len({r['instrument_id'] for r in rows})
    return {'method':'scan-funnel-v1','scan_id':scan_id,'strategy_id':scan['strategy_version_id'],
        'as_of':scan['data_cutoff'],'job_status':scan['status'],'unique_instruments':instruments,
        'candidate_instruments':metrics.get('candidates_total'),'candidate_failures':metrics.get('candidate_failures'),
        'assessments':len(rows),'by_horizon':dict(horizons),'usable_assessments':usable,
        'score_qualified':score_qualified,'veto_free_qualified':qualified,
        'execution_eligible':sum(o['entry_decision']=='allow' for o in orders),
        'execution_not_checked':sum(o['entry_decision'] is None for o in orders),
        'submitted':sum(o['submitted_at'] is not None for o in orders),
        'filled':sum(o['has_fill'] for o in orders),'primary':dict(primary),'secondary':dict(secondary),
        'score_bands':dict(bands),'thresholds':limits,
        'coverage_note':'Usable means legacy weighted-pillar completeness threshold; individual feature coverage may be incomplete.',
        'execution_note':'Latest recorded entry checks for existing intents; absence of an intent is not proof of execution eligibility.'}


def capture(db, scan_id):
    if not present(db,'scan_diagnostic_snapshots'):return
    result=diagnostic(db,scan_id)
    with db:db.execute('INSERT OR IGNORE INTO scan_diagnostic_snapshots VALUES (?,?,?,?)',
        (scan_id,result['method'],datetime.now(timezone.utc).isoformat(),canonical(result)))


def backfill(db, limit=4):
    if not present(db,'scan_diagnostic_snapshots'):return
    rows=db.execute("SELECT id FROM scan_runs WHERE status IN ('succeeded','partial') AND id NOT IN (SELECT scan_id FROM scan_diagnostic_snapshots) ORDER BY scheduled_for DESC LIMIT ?",(limit,)).fetchall()
    for row in rows:capture(db,row['id'])
