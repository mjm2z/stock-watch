# StockWatch effectiveness review — September 22, 2026

Assessment based on the working tree, earlier release records, and read-only checks of a1347-j around 10:06–10:10 AM Eastern. No strategy, orders, services, or production data were changed. The working tree already contains substantial uncommitted September improvements; those were preserved.

## Conclusion

The application has a substantial research/execution foundation, but there is not yet evidence of a profitable trading edge. Its first recorded paper fills are September 18. There are no closed lots, no completed outcomes in the overview, and no backtests returned by the live backtest endpoint. The immediate priorities are reliable collection, execution/evaluation alignment, and valid data—not tuning weights to the first profitable position.

Mike confirmed the primary success criterion: net return above SPY, with controlled drawdown. Report win rate, average win/loss, exposure, and total portfolio return alongside it. A higher win rate can coexist with worse returns if losses are larger than wins.

Evaluate candidate changes by out-of-sample excess return after costs and maximum drawdown, using consistent capital, cash-flow, and benchmark timing assumptions. Show whole-budget performance including idle cash alongside invested-capital performance. Treat win rate as diagnostic rather than the optimization target. A numerical drawdown limit has not yet been specified; report absolute drawdown and its difference from SPY, and do not invent an approved risk limit.

## Purpose and decision process

The Next.js dashboard presents a Python worker's durable SQLite research and Alpaca paper-trading records. Shared watchlists and research notes support manual investigation. The legacy AI analysis is disabled by default and is not the automated trading decision engine.

The automated strategy is a deterministic, long-only S&P 500 ranking system:

1. Resolve a versioned universe; collect Alpaca IEX adjusted daily bars, news, and tradable/fractional eligibility. Load cached SEC CompanyFacts using the signal cutoff.
2. Compute six pillars: momentum 25%, quality 20%, valuation 15%, news 15%, market regime 10%, risk/liquidity 15%. Available pillars are renormalized when others are missing.
3. Apply score >=75, weighted pillar completeness >=80%, and low/medium risk requirements. Risk becomes high if any of liquidity below $20M, volatility above 60%, or drawdown worse than -30% applies.
4. Persist the same baseline ranking for 5/21/63/105 trading-session horizons. These are four holding-period observations, not four independent forecasts. Opening scans exclude the unfinished current daily bar; closing scans include the current session.
5. Paper-v2 checks underlying input coverage, anomalies, and freshness, then allocates in descending score order. It reserves $5–$15 lots within $30 per stock, $60 per sector, and $300 total committed capital across versions. Horizon priority is 21, 5, 63, 105.
6. Check broker reconciliation, account/cash, quote age <=120 seconds, spread <=1%, and ask-price movement <=5% from the frozen reference. Known nearby earnings block entry, but comprehensive earnings coverage is unavailable.
7. Closing-scan intents wait until the next session at 9:45 AM and expire at 10 AM. Opening signals expire 30 minutes after assessment. Deterministic broker IDs support retry reconciliation.
8. Time-based exits follow actual entry-session holding periods. Forward research outcomes instead enter at the next session open and exit at the horizon close, with 10 basis points modeled round-trip cost and matched SPY sessions.

Main sources: `strategy.py`, `features.py`, `scan_data.py`, `scan_executor.py`, `assessment.py`, `assessment_release.py`, `paper_orders.py`, `entry_controls.py`, `paper_lifecycle.py`, `forward_outcomes.py`.

## Daily operations

| Process | Schedule | What it does |
| --- | --- | --- |
| Backup | 04:30 UTC plus up to 10 minutes | Consistent SQLite backup and verification; configured retention |
| SEC refresh | 06:15 UTC plus up to 10 minutes | Refresh CompanyFacts independently of scans |
| Universe | Weekdays 5:30 AM Eastern plus up to 5 minutes | Validate approved constituent CSV, update snapshot and eligibility |
| Dispatcher | Every 5 minutes | Exchange-calendar-aware scan creation; 20-minute catch-up window |
| Scans | Open +15 minutes / close +15 minutes | Normally 9:45 AM / 4:15 PM Eastern; holiday and early-close handling |
| Worker | Every minute | Due entry checks, queued scan processing, bounded retries and stale-job recovery |
| Maintenance | Weekdays 10:15 AM / 5:15 PM Eastern | Reconcile fills, due exits, broker positions, mature outcomes, portfolio/SPY snapshots |

The UTC overnight schedules shift their Eastern wall-clock times with DST. In September, backups start around 12:30 AM and fundamentals around 2:15 AM Eastern. There is no scheduled backtest or automatic strategy learning/promotion job in these units.

All six live timers were active. Latest backup, fundamentals and universe services succeeded. Worker/dispatcher ticks succeeded, but the latest actual scan failed: timer health and successful trading work are separate measures.

## Measured progress

| Measure | Observed result |
| --- | --- |
| Selected strategy | `sp500-long-paper-v2`, paper, since September 17 |
| Six most recent scheduled scans | 3 succeeded, 3 failed |
| Failed scans in that window | September 18 close, September 21 open, September 22 open |
| Common failure | Updated Alpaca news conflicts with immutable article row |
| Last successful scan | September 21 close: 503 companies, 2,012 horizon records, 8 baseline-qualified records |
| Actual filled holdings at inspection | Four MRK horizon lots, opened September 18 |
| Pending local holdings | Four MSFT horizon lots, broker status recorded as submitted |
| Closed lots / realized P&L | 0 / $0 |
| Completed overview outcomes | 0 |
| Live backtest list | Empty |
| Latest portfolio valuation time | September 21, 5:15 PM Eastern |
| Filled contributed capital | $25.96 |
| Unrealized P&L | +$0.61, approximately +2.36% on filled capital |
| Contribution-matched SPY comparison | Approximately +1.61%; excess +$0.20 / +0.75 percentage points |
| Filled cost plus pending commitments | Approximately $55.96, including $30 pending MSFT |
| First MRK target exit | September 24 at 4 PM Eastern |

The displayed `openLots=8` includes pending lots. It does not mean eight confirmed fills. The +2.36% is neither a return on the full $300 budget nor a realized return. SPY timing and adjusted-price caveats below also limit interpretation. Four MRK horizons represent one stock exposure so far, not four independent successes.

The eight latest baseline qualifications are MSFT and VLO, each across four horizons. VLO has only 76.47% underlying metric coverage and its order intents were rejected by the data review. Thus eight qualifications do not mean eight executable opportunities.

Earlier records document recovery from a development-only strategy, immutable-bar ingestion failures, and excessive SEC-loader memory. The current paper fills demonstrate meaningful execution progress. The September evaluation fixes, shared research, allocation controls, and shadow assessments are present in the reviewed code; current live policy and decision evidence confirm v2 activation.

## Improvements, in priority order

### 1. Version news revisions without losing point-in-time evidence — immediate

`ingestion.py:persist_news_articles` hashes the entire article payload and raises `DataConflictError` when the same article ID changes. One revision aborts the whole scan. This explains all three recent failed scans; the September 22 error identifies `alpaca:61860049`.

Store immutable article revisions with provider update time, first-observed time, content hash, symbol associations, and sentiment-model version. Pin each scan to its exact revision. Do not overwrite historical text or simply ignore all changed news. `_load_news` currently filters publication time only; later article edits must not be admitted to an earlier cutoff merely because the original article was published earlier.

Regression requirements: a harmless provider update must not abort 503-company scoring; future revisions cannot change earlier features; retries preserve the same frozen evidence. Track missed scans and affected candidate coverage. If degraded collection is supported, persist explicit missing-data states under a versioned policy.

### 2. Make executable entry/exit timing match the evaluation — immediate

`paper_lifecycle.py` creates exit intents only once `now >= target_exit_at`; maintenance runs at 5:15 PM. The broker payload is a regular DAY market sell. This cannot obtain the already elapsed 4 PM close. Expect next-session execution under regular-hours routing, subject to broker acceptance. This is a code/schedule finding, not an observed failed exit: no lot has matured yet.

Choose and version a supported exit contract: schedule execution before the target close with suitable fractional-order support, or deliberately use next-session execution and model it. Do not assume market-on-close support for this fractional order path. Test early closes, holidays, rejection/cancellation recovery, partial fills, and the September 24 first exit end to end before interpreting a completed result.

Opening paper entries occur the same morning, whereas their research labels start the following session. Closing paper entries wait until 9:45 AM, whereas research uses 9:30 AM. Keep standardized ranking outcomes, but add a simulation that reproduces actual executable timing and quote/capacity gates.

### 3. Correct the liquidity measurement before changing thresholds — high

The latest successful scan has 315 high-risk companies out of 503. Of these, 264 are high-risk solely because IEX dollar volume is below the threshold; 276 total have low volume, 30 volatility triggers, and 36 drawdown triggers (overlapping groups). No company is rejected solely on risk in that scan.

IEX measures one exchange, while SIP consolidates exchanges. Comparing IEX volume with market-wide liquidity expectations distorts both the veto and the score. Removing the veto alone would not qualify those companies because their existing scores also fail.

Compare completed-session IEX and SIP bars, investigate outlier prices/corporate actions, and recompute both ranking and risk on a separate dataset. Alpaca documents historical SIP access for requests ending at least 15 minutes in the past without a subscription; verify actual entitlement before assuming a paid plan is necessary. Retain IEX's identity on quote checks and distinguish its spread from consolidated NBBO.

### 4. Repair financial comparability and remaining point-in-time gaps — high

Confirmed code limitations in `sec_fundamentals.py`:

- Quality and valuation flow measures use annual 10-K values rather than current TTM/quarterly trends.
- `_best_annual_series` prefers the concept with the most historical observations, before recency. A long discontinued revenue tag can beat a shorter current tag. Select a coherent, current series using metric-specific provenance.
- Freshness uses the maximum filing date across all selected facts. A recent share count or comparative restatement can make old annual operating data appear fresh. Track fiscal period end and availability per metric.
- Filings are filtered by calendar date, not EDGAR acceptance time. In historical replay, an after-close filing on the signal date could be used too early. Use actual availability timestamps or a conservative next-session rule. Live cached-document capture time helps but does not eliminate the historical issue.
- Fixed margin, leverage, and P/E scoring scales apply across sectors. Missing negative earnings/equity may remove unfavorable inputs rather than explicitly represent distress. Evaluate sector-appropriate metrics and explicit missing/distressed categories.

Build audited fixtures for renamed XBRL tags, stale annual periods, restatements, negative equity, share-class differences, and stock splits. Validate units and adjustment consistency between EPS, shares, prices, and cash flows before adding financial complexity.

### 5. Establish an honest baseline experiment before tuning — high

Backtest infrastructure exists, including costs, chronological splits, complete-label validation cutoffs, Wilson intervals, immutable manifests, and point-in-time universe support. There is no completed run visible on the live endpoint.

Run a frozen baseline on validated historical data, then compare a small preregistered set: baseline, no-news, horizon-specific weighting, and simple momentum/quality controls. Shadow assessments already record the first three variants, including rejected candidates; they do not automatically change trading. Their alternative weights are hypotheses, not learned improvements.

Required evaluation additions:

- Reproduce $300 total/$60 sector/$30 stock capacity, cash, score-ranked allocation, actual sizing configuration, and executable entry/exit times. Current backtests use independently funded lots, and `_prepare_signals` still calls default sizing instead of the version's sizing policy.
- Report each horizon separately, with unique companies, entry dates, market regimes, net expectancy, average win/loss, profit factor, drawdown, exposure, and excess return over SPY. Also show whole-budget return including idle cash.
- Estimate uncertainty with time/cohort-aware resampling; repeated stocks and overlapping holding windows are not independent Bernoulli trials. Purge incomplete labels and retain an untouched final test period.
- Record every attempted variant. Compare costs and slippage scenarios; promote only a version that shows repeatable out-of-sample improvement, then confirm in forward paper results.

### 6. Align portfolio accounting and status with what they claim — high/medium

`portfolio_snapshots.py` values actual broker quantities against adjusted historical closes. That mixes execution accounting with a research price series; dividends are not attributed to lots, and splits require explicit reconciliation. Use raw tradable marks plus a corporate-action/dividend ledger for broker P&L, and a separately defined total-return series for research.

Its SPY cohort enters at the actual fill session's daily open, although MRK fills occurred around 9:51–9:52 AM. This matches sessions and contributions, not execution timestamps. For execution alpha, benchmark SPY at aligned timestamps or disclose the timing difference prominently.

Show score-qualified, data-approved, allocation-approved, submitted, filled, exited, and evaluated counts separately. VLO is a concrete example of why this matters. Refresh in-flight fills independently of new entry demand: the minute worker chiefly handles pending entries, while submitted fills may remain locally pending until maintenance. A stale status alone does not establish broker failure.

### 7. Refine the strategy only after the above evidence exists — experiments

- Test the 15% news contribution. The current small lexicon can saturate on a few words, lacks robust relevance/entity handling, and treats no articles as neutral when coverage is marked complete. Deduplicate event coverage and test relevance/recency before adding a larger model.
- Consider separate paper allocations by horizon or one selected horizon per company. Four lots in the same stock consume capacity and create correlated observations. Long horizons lock capital for months; more lots do not automatically increase learning or diversification.
- Add verified earnings coverage and measure performance through earnings versus outside earnings windows. A 24-hour entry filter alone does not describe earnings exposure across a 105-session holding period.
- Test regime-aware exposure and sector-relative ranking against simple controls. The current common market-regime score changes broad qualification, while correlated momentum inputs may double-count trends.
- Evaluate exit alternatives using loss severity and net expectancy. Do not add stop-loss/take-profit rules solely to raise win rate; they change the return distribution and require separate cost-aware testing.

## Verification and limits

245 Python tests and 42 JavaScript tests passed during this review. These verify covered behavior, not financial efficacy. SHA-256 hashes for seven key source modules matched `/opt/stock-watch/worker/src` on the server: ingestion, lifecycle, fundamentals, entry controls, scan data, backtest runner, and portfolio snapshots. This was not a full installed-package audit.

Live findings came from dashboard execution, overview, portfolio, liquidity, health and backtest APIs, plus systemd timer/service status. Direct database listing was denied by host permissions; no permissions were changed. An empty live backtest list does not exclude experiments stored elsewhere. The review did not independently reconcile every broker fill or audit raw historical provider data. Production records can advance after the stated observation time.

## Provider references

- [Alpaca market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq): IEX versus SIP, delayed historical SIP access, corporate-action/symbol handling.
- [Alpaca order documentation](https://docs.alpaca.markets/us/docs/orders-at-alpaca): regular/extended-hours behavior and order constraints.
- [Alpaca paper trading](https://docs.alpaca.markets/us/docs/paper-trading): simulation limits, including market impact, latency slippage, queue position and dividend treatment. Paper profitability alone does not validate live execution.

Recommended sequence: repair news revision handling; settle and verify exit timing; validate data/financial inputs and accounting; produce a reproducible baseline; then use held-out and forward evidence to choose strategy changes.

Implementation follow-up: the news revision repair and independently scheduled
five-minutes-before-close exit policy are implemented and tested in the
[September 22 reliability release](reliability-release-2026-09-22.md). Mike
explicitly selected this exit timing. The release was installed on a1347-j at
10:58:32 AM Eastern; successful exit ticks and updated submission targets were
verified. The next live collection and actual exit remain to be observed. The
measured production findings above remain the original review snapshot.
