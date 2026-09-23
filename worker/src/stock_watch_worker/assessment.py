"""Transparent input reviews and observation-only scoring alternatives."""
from __future__ import annotations
import json
from datetime import date
from .domain import ScoreRequest
from .strategy import calculate_score

VERSION = "assessment-review-v1"
EXPECTED = {"momentum":5,"quality":4,"valuation":2,"market_regime":3,"risk_liquidity":3}
HORIZON_WEIGHTS = {
    5: {"momentum":.45,"quality":.10,"valuation":.05,"news":.05,"market_regime":.15,"risk_liquidity":.20},
    21:{"momentum":.35,"quality":.20,"valuation":.10,"news":.05,"market_regime":.10,"risk_liquidity":.20},
    63:{"momentum":.25,"quality":.30,"valuation":.20,"news":.05,"market_regime":.10,"risk_liquidity":.10},
    105:{"momentum":.15,"quality":.35,"valuation":.25,"news":.05,"market_regime":.10,"risk_liquidity":.10},
}

def review_inputs(candidate, features, as_of, spy_bars=()):
    bars=candidate.bars
    warnings=[]; blockers=[]
    if len(bars)<200:blockers.append("insufficient_price_history")
    anomalies=[{"session":b.session,"return":b.close/a.close-1} for a,b in zip(bars,bars[1:]) if abs(b.close/a.close-1)>.40]
    if anomalies:blockers.append("price_jump_requires_verification")
    expected_sessions={b.session for b in spy_bars[-63:]}
    missing=sorted(expected_sessions-{b.session for b in bars})
    if missing:blockers.append("missing_market_sessions")
    if bars and (date.fromisoformat(as_of[:10])-date.fromisoformat(bars[-1].session)).days>7:blockers.append("stale_price_history")
    if candidate.fundamentals is None: warnings.append("fundamentals_unavailable")
    elif (date.fromisoformat(as_of[:10])-date.fromisoformat(candidate.fundamentals.as_of[:10])).days>450:blockers.append("stale_financial_statements")
    coverage={name: {"available":min(features.pillars[name].source_count,total),"expected":total} for name,total in EXPECTED.items()}
    percent=100*sum(v['available'] for v in coverage.values())/sum(EXPECTED.values())
    if percent<80:blockers.append("insufficient_underlying_metrics")
    return {"version":VERSION,"blockers":blockers,"warnings":warnings,"metric_coverage":round(percent,2),"pillars":coverage,"anomalies":anomalies,"missing_sessions":missing,
            "news_articles":features.raw.get("news_article_count"),"fundamental_ratio":"total liabilities / equity; not debt / equity"}

def persist_assessments(connection, signal_id, candidate, features, horizon, policy, weights, quality, at):
    variants={"baseline-v1":dict(weights),"horizon-weights-v1":HORIZON_WEIGHTS[horizon]}
    # Ablation preserves the other relative weights; it does not replace missing news with optimism.
    without={name:(value/(1-weights['news']) if name!='news' else 0) for name,value in weights.items()}
    variants['without-news-v1']=without
    with connection:
        connection.execute("INSERT INTO assessment_reviews VALUES (?,?,?,?) ON CONFLICT DO NOTHING",(signal_id,at,json.dumps(quality,sort_keys=True),VERSION))
        for name,variant_weights in variants.items():
            effective={k:v for k,v in variant_weights.items() if v>0}
            result=calculate_score(ScoreRequest(candidate.symbol,features.pillars,features.risk_level,candidate.vetoes),weights=effective,policy=policy)
            reasons=list(result.reasons)+["data:"+v for v in quality['blockers']]
            config={"version":name,"weights":variant_weights,"minimum_score":policy.minimum_score,"minimum_completeness":policy.minimum_data_completeness,"allowed_risks":[str(v) for v in policy.allowed_risk_levels],"orders_enabled":False,"data_review":VERSION}
            connection.execute("INSERT INTO shadow_assessments VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",(signal_id,name,result.opportunity_score,int(not reasons),json.dumps(reasons),json.dumps(config,sort_keys=True),at))
