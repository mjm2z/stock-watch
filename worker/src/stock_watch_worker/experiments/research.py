"""Bounded, immutable proposals. Research never changes execution authority."""
from .model import config, canonical, digest, stamp
from .store import transaction, register

def propose(db,now):
    week=now.date().isocalendar(); key=f'{week.year}-W{week.week:02d}'
    with transaction(db):
        for asset in ('stocks','bitcoin'):
            for family in ('trend','breakout','reversal','news_breakout'):
                for variant in (1,2):
                    cfg=config(asset,family,variant); version=register(db,cfg,now)
                    baseline=config(asset,family)
                    changed={k:{'before':baseline[k],'after':v} for k,v in cfg.items() if baseline[k]!=v and k!='variant'}
                    identifier=digest({'asset':asset,'family':family,'week':key,'variant':variant})
                    evidence={'hypothesis':'Test sensitivity to one predefined threshold; no claimed profitability',
                        'changes':changed,'baseline':digest(baseline),'requires':'New frozen batch approval',
                        'sources':[{'url':'https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data','role':'feed semantics'},
                                   {'url':'https://docs.alpaca.markets/us/docs/paper-trading','role':'simulation limitations'}],
                        'context':'SEC company/filing and macro research remain context; news presence is not sentiment'}
                    db.execute('INSERT OR IGNORE INTO experiment_research_proposals VALUES (?,?,?,?,?,?,?,?)',
                        (identifier,asset,family,key,variant,version,canonical(evidence),stamp(now)))
