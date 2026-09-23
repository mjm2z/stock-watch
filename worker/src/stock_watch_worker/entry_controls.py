"""Entry-time checks. Decisions are durable; a deferred order is not submitted."""
from __future__ import annotations
import json, math
from datetime import datetime, timedelta, timezone
from .market_calendar import utc_iso


def aware(value):
    parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed


def check_entry(connection, order_id, broker, now):
    row=connection.execute("""SELECT o.*,s.as_of,s.instrument_id,s.feature_snapshot_id,
        v.config_json,i.symbol FROM paper_orders o JOIN signals s ON s.id=o.signal_id
        JOIN strategy_versions v ON v.id=s.strategy_version_id JOIN instruments i ON i.id=s.instrument_id
        WHERE o.id=?""",(order_id,)).fetchone()
    policy=json.loads(row['config_json']).get('entry_policy',{})
    if not policy.get('enabled'): return 'allow','legacy_policy'
    existing=connection.execute('SELECT * FROM deferred_entries WHERE order_id=?',(order_id,)).fetchone()
    if existing and existing['state']=='rejected': return 'reject','signal_expired'
    deadline = aware(existing['expires_at']) if existing else aware(row['as_of']) + timedelta(minutes=policy.get('maximum_initial_signal_age_minutes',30))
    if now > deadline:
        return _record(connection,row,'reject','signal_expired',{},now)
    if existing and now < aware(existing['next_check_at']):
        return 'defer','waiting_for_scheduled_check'
    # Use the frozen score input price, not an unrelated later cache price.
    features=connection.execute('SELECT features_json FROM feature_snapshots WHERE id=?',(row['feature_snapshot_id'],)).fetchone()
    raw=json.loads(features[0]).get('raw',{}) if features else {}
    reference_price=raw.get('reference_close')
    details={'quote_feed':'iex','policy':policy}
    try:
        context=broker.get_entry_context(str(row['symbol']))
        clock=context['clock']; account=context['account']; quote=context.get('quote')
        checked=aware(clock['timestamp'])
        if abs((checked-now).total_seconds())>300: return _record(connection,row,'defer','broker_clock_stale',details,now)
        if existing and checked>aware(existing['expires_at']):
            return _record(connection,row,'reject','signal_expired',details,checked)
        if not existing and (checked-aware(row['as_of'])).total_seconds()>policy.get('maximum_initial_signal_age_minutes',30)*60:
            return _record(connection,row,'reject','signal_expired',details,checked)
        if account.get('status')!='ACTIVE' or account.get('trading_blocked') or account.get('account_blocked') or account.get('trade_suspended_by_user'):
            return _record(connection,row,'reject','broker_account_blocked',details,checked)
        if not isinstance(reference_price,(int,float)) or not math.isfinite(reference_price) or reference_price<=0:
            return _record(connection,row,'reject','reference_price_unavailable',details,checked)
        if existing is None:
            opens=aware(clock['next_open'])
            expires=(aware(row['as_of'])+timedelta(minutes=policy.get('maximum_initial_signal_age_minutes',30))) if clock['is_open'] else opens+timedelta(minutes=30)
            next_check=checked if clock['is_open'] else opens+timedelta(minutes=15)
            with connection:
                connection.execute('INSERT INTO deferred_entries VALUES (?,?,?,?,?)',(order_id,utc_iso(next_check),utc_iso(expires),reference_price,'waiting'))
        if not clock['is_open']:
            return _record(connection,row,'defer','waiting_for_regular_session',details,checked)
        reconciliation=connection.execute('SELECT status,captured_at FROM broker_reconciliations ORDER BY captured_at DESC,id DESC LIMIT 1').fetchone()
        if reconciliation is None or reconciliation['status']!='matched' or (checked-aware(reconciliation['captured_at'])).total_seconds()>300:
            return _record(connection,row,'defer','broker_reconciliation_stale',details,checked)
        if quote is None: return _record(connection,row,'defer','fresh_quote_unavailable',details,checked)
        bid=float(quote['bp']); ask=float(quote['ap']); quote_time=aware(quote['t'])
        if not all(math.isfinite(v) and v>0 for v in (bid,ask)) or ask<bid:
            return _record(connection,row,'defer','invalid_quote',details,checked)
        age=(checked-quote_time).total_seconds(); spread=(ask-bid)/((ask+bid)/2)
        gap=abs(ask/reference_price-1)
        details.update({'bid':bid,'ask':ask,'quote_at':utc_iso(quote_time),'quote_age_seconds':age,'spread_fraction':spread,'reference_price':reference_price,'price_change_fraction':gap})
        if age< -5 or age>policy.get('maximum_quote_age_seconds',120): return _record(connection,row,'defer','stale_quote',details,checked)
        if spread>policy.get('maximum_spread_fraction',.01): return _record(connection,row,'defer','spread_too_wide',details,checked)
        if gap>policy.get('maximum_price_change_fraction',.05): return _record(connection,row,'reject','entry_price_moved',details,checked)
        commitment=connection.execute("SELECT COALESCE(SUM(notional_usd),0) FROM paper_orders WHERE id!=? AND status IN ('pending','submitted','accepted','partially_filled')",(order_id,)).fetchone()[0]
        available=min(float(account['cash']),float(account['buying_power']))
        if not math.isfinite(available) or available-commitment<float(row['notional_usd']):return _record(connection,row,'reject','insufficient_unreserved_cash',details,checked)
        event=connection.execute('SELECT earnings_at,captured_at FROM instrument_context WHERE instrument_id=?',(row['instrument_id'],)).fetchone()
        if event and event['earnings_at']:
            if abs((aware(event['earnings_at'])-checked).total_seconds())<policy.get('earnings_buffer_hours',24)*3600:
                return _record(connection,row,'reject','earnings_window',details,checked)
        else:
            details['earnings_coverage']='unknown; no verified event feed configured'
            if policy.get('require_earnings_calendar',False):return _record(connection,row,'reject','earnings_calendar_unavailable',details,checked)
        return _record(connection,row,'allow','entry_checks_passed',details,checked)
    except Exception as error:
        details['error_type']=type(error).__name__
        return _record(connection,row,'defer','entry_verification_unavailable',details,now)


def _record(connection,row,decision,reason,details,now):
    at=utc_iso(now)
    with connection:
        connection.execute('INSERT INTO entry_checks(order_id,checked_at,decision,reason,details_json) VALUES (?,?,?,?,?)',(row['id'],at,decision,reason,json.dumps(details,sort_keys=True)))
        previous=connection.execute("SELECT error FROM paper_orders WHERE id=?",(row['id'],)).fetchone()[0]
        if decision!='allow':
            connection.execute('UPDATE paper_orders SET error=?,updated_at=? WHERE id=?',(reason,at,row['id']))
        if decision=='reject':
            connection.execute("UPDATE paper_orders SET status='rejected' WHERE id=?",(row['id'],))
            connection.execute("UPDATE paper_trade_lots SET status='canceled' WHERE entry_order_id=? AND status='pending'",(row['id'],))
            connection.execute("UPDATE deferred_entries SET state='rejected' WHERE order_id=?",(row['id'],))
        if decision=='defer' and reason!='waiting_for_regular_session':
            connection.execute('UPDATE deferred_entries SET next_check_at=? WHERE order_id=?',(utc_iso(now+timedelta(minutes=1)),row['id']))
        if previous!=reason:
            connection.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,payload_json) VALUES ('paper_entry_check','paper_order',?,?)",(row['id'],json.dumps({'decision':decision,'reason':reason,**details},sort_keys=True)))
    return decision,reason


def process_deferred_entries(connection,broker,now):
    from .paper_orders import submit_or_reconcile_order
    rows=connection.execute("""SELECT o.id FROM paper_orders o JOIN signals s ON s.id=o.signal_id
        JOIN strategy_versions v ON v.id=s.strategy_version_id LEFT JOIN deferred_entries d ON d.order_id=o.id
        WHERE o.status='pending' AND json_extract(v.config_json,'$.entry_policy.enabled')=1
        AND (d.order_id IS NULL OR (d.state='waiting' AND d.next_check_at<=?))
        ORDER BY s.opportunity_score DESC,s.as_of DESC,o.id LIMIT 30""",(utc_iso(now),)).fetchall()
    for row in rows:submit_or_reconcile_order(connection,order_id=row['id'],broker=broker,now=now)
    return len(rows)


def prepare_due_entries(connection, broker, now):
    """Avoid overnight polling and reconcile existing fills before checking drift."""
    due = connection.execute("""SELECT 1 FROM paper_orders o
        JOIN signals s ON s.id=o.signal_id JOIN strategy_versions v ON v.id=s.strategy_version_id
        LEFT JOIN deferred_entries d ON d.order_id=o.id
        WHERE o.status='pending' AND json_extract(v.config_json,'$.entry_policy.enabled')=1
        AND (d.order_id IS NULL OR (d.state='waiting' AND d.next_check_at<=?)) LIMIT 1""", (utc_iso(now),)).fetchone()
    if due is None:
        return False
    from .paper_orders import submit_or_reconcile_order
    from .broker_reconciliation import capture_and_reconcile_broker
    inflight = connection.execute("SELECT id FROM paper_orders WHERE status IN ('submitted','accepted','partially_filled')").fetchall()
    for order in inflight:
        submit_or_reconcile_order(connection, order_id=order['id'], broker=broker, now=now)
    capture_and_reconcile_broker(connection, broker=broker, captured_at=now)
    return True
