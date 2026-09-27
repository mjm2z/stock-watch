"""Prospective, shadow-only fundamentals v2. Baseline annual inputs stay frozen."""
from datetime import date, datetime
import math

VERSION='fundamentals-review-v2'


def available(entry, decision_at, sessions):
    accepted=entry.get('accepted') or entry.get('acceptanceDateTime')
    if accepted:
        try:
            at=datetime.fromisoformat(str(accepted).replace('Z','+00:00'))
            decision=datetime.fromisoformat(decision_at.replace('Z','+00:00'))
            return at.tzinfo is not None and at<=decision
        except (TypeError,ValueError):return False
    filed=str(entry.get('filed',''))
    # Without acceptance time, wait until the next verified exchange opening.
    opening=next((opened for day,opened in sessions if day>filed),None) if filed else None
    try:
        opened = datetime.fromisoformat(str(opening).replace('Z', '+00:00'))
        decision = datetime.fromisoformat(decision_at.replace('Z', '+00:00'))
        return opened.tzinfo is not None and decision.tzinfo is not None and opened <= decision
    except (TypeError, ValueError):
        return False


def ttm(entries, decision_at, sessions):
    points=[]
    for e in entries:
        if e.get('form') not in ('10-Q','10-K') or not available(e,decision_at,sessions):continue
        try:
            start,end=date.fromisoformat(e['start']),date.fromisoformat(e['end'])
            value=float(e['val'])
            if end.isoformat()>decision_at[:10] or not math.isfinite(value) or not 55<=(end-start).days<=430:continue
            points.append((start,end,value,e))
        except (KeyError,ValueError,TypeError):continue
    latest=max((p[1] for p in points),default=None)
    by_period={}
    for p in points:
        if latest and (latest-p[1]).days<=800:
            key=(p[0],p[1]);old=by_period.get(key)
            if old is None or str(p[3].get('filed',''))>str(old[3].get('filed','')):by_period[key]=p
    points=list(by_period.values())
    quarters={}
    def save(start,end,value,refs):
        key=(start,end)
        stamp=max(str(r.get('filed','')) for r in refs)
        if key not in quarters or stamp>quarters[key]['filed']:
            quarters[key]={'start':start,'end':end,'value':value,'filed':stamp,
                           'accessions':sorted({str(r.get('accn','unknown')) for r in refs})}
    for start,end,value,e in points:
        if 55<=(end-start).days<=120:save(start,end,value,[e])
        for prior_start,prior_end,prior_value,prior in points:
            # Prefer explicitly reported quarters; only subtract same fiscal
            # year's cumulative values, never unrelated quarters or periods.
            if prior_start==start and 55<=(end-prior_end).days<=120 and prior_end<end:
                from datetime import timedelta
                save(prior_end+timedelta(days=1),end,value-prior_value,[prior,e])
    ordered=sorted(quarters.values(),key=lambda q:(q['end'],q['filed']),reverse=True)
    chosen=[]
    for q in ordered:
        if not chosen or 0<=(chosen[-1]['start']-q['end']).days<=3:
            chosen.append(q)
        if len(chosen)==4:break
    if len(chosen)!=4 or not 300<=(chosen[0]['end']-chosen[-1]['start']).days<=430:
        return {'available':False,'reason':'Four compatible, available fiscal quarters are not retained'}
    return {'available':True,'value':sum(q['value'] for q in chosen),
            'start':chosen[-1]['start'].isoformat(),'end':chosen[0]['end'].isoformat(),
            'quarters':[{**q,'start':q['start'].isoformat(),'end':q['end'].isoformat()} for q in reversed(chosen)]}


def review(facts, decision_at, sessions):
    definitions={'revenue':('RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'),
                 'net_income':('NetIncomeLoss','ProfitLoss'),
                 'operating_cash_flow':('NetCashProvidedByUsedInOperatingActivities',),
                 'capex':('PaymentsToAcquirePropertyPlantAndEquipment','PaymentsForAdditionsToPropertyPlantAndEquipment')}
    us=facts.get('facts',{}).get('us-gaap',{})
    result={'version':VERSION,'authority':'shadow only','available_at_rule':'Acceptance timestamp, otherwise next verified exchange open after filing date','metrics':{}}
    for name,concepts in definitions.items():
        values=[(concept,ttm(us.get(concept,{}).get('units',{}).get('USD',[]),decision_at,sessions)) for concept in concepts]
        concept,value=next(((c,v) for c,v in values if v['available']),values[0])
        result['metrics'][name]={**value,'concept':concept,'unit':'USD'}
    periods={(v['start'],v['end']) for v in result['metrics'].values() if v['available']}
    result['compatible_periods']=len(periods)==1 and all(v['available'] for v in result['metrics'].values())
    return result
