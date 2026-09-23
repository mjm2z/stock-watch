# Assessment controls release — September 17, 2026

## Status

Implemented and staged for installation on a1347-j. Production activation requires
`sudo bash ~/stock-watch-assessment-20260917/deploy/install-assessment-root.sh`.
The installer runs as a detached systemd unit and reports progress without a pager.
Do not describe the release as live until its service finishes and the dashboard
and worker checks confirm the selected policy.

## Execution policy

New immutable `sp500-long-paper-v2`, cloned from the hash-checked paper-v1 config.
Baseline scoring weights and qualification thresholds are retained. Correct the
financial label to **total liabilities / equity**; the underlying calculation is
unchanged. Sizing now uses the stored bands and risk multiplier.

User-approved allocation: **$300 portfolio, $60 per sector, $30 per stock,
$5–$15 per order**. Entry cost for pending, open and closing lots reserves capacity
across strategy versions. Closed/canceled lots release it. This is a committed
capital limit, not a cap on market-value appreciation or cumulative lifetime buys.
SQLite serializes capacity checks and reservation across workers. Missing sector
classifications share one $60 Unknown bucket. Universe refresh imports validated
GICS labels from the existing approved CSV, including the cached CSV's sector
column. No new market-data subscription is used.

The entire scan is scored before allocation, descending score then ticker for ties.
Within each stock, horizon priority is 21, 5, 63, 105 sessions. Multiple horizon lots
still share the same $30 stock allocation. Existing time-based exits remain intact.

Before an entry is prepared, block insufficient price history, missing recent SPY
comparison sessions, bars older than seven calendar days, daily adjusted-price
jumps above 40%, fundamentals whose filing timestamp is older than 450 days, and
underlying metric coverage below 80%. Coverage counts individual available inputs,
not just whether a pillar has any score. These conservative anomaly checks flag
unverified observations; they do not claim a provider error or a corporate action.

Before submission, reconcile by the deterministic client order ID first. An order
already at the broker is reconciled even if the signal has since expired. New
submissions require an active/unblocked paper account, a recent matched broker
reconciliation, an IEX quote no older than 120 seconds, bid–ask spread <=1%, and
ask price within 5% of the frozen assessment close. Cash/buying power must cover
other pending commitments plus the entry. This cash check is conservative because
the broker may already reserve some of those commitments in buying power.

Closing scans hold intents locally until the next exchange session at 9:45 AM ET;
new entries expire at 10 AM. Opening signals expire 30 minutes after the assessment timestamp; retries do
not extend that window. Maintenance cannot
bypass a future check time. Deferred entries do not poll the broker overnight;
existing in-flight fills are reconciled before taking the next due-entry position
snapshot, avoiding false drift from newly completed fills. Quotes/provider failures defer without submitting;
price movement, blocked accounts, inadequate cash, known nearby earnings and
expired signals reject and release local pending lots. If broker lookup itself
fails, the intent stays reserved until submission uncertainty can be resolved.

## Research

Every new signal, including rejected signals, records the input-quality review and
three immutable observation-only assessments:

- Baseline weights with the same new data-quality checks.
- Horizon-specific alternative weights.
- News-weight ablation, renormalizing the remaining weights.

Alternatives never route orders and cannot automatically promote themselves.
Rejected/near-threshold candidates receive the same finalized forward-outcome
measurement as qualified signals. The overview's qualified-signal metrics exclude
those rejected observations. Research groups by strategy, horizon, variant and
stored configuration; it displays observed/qualified/matured counts, modeled net
return and excess return/beat rate versus SPY. Repeated and overlapping signals
are correlated; 30 observations is only an early-sample label, not proof of an edge.
Outcome windows use next-session open through horizon close and the existing
10-basis-point round-trip model. They do not simulate allocation or quote gates,
and they are not actual paper-fill performance.

## Dashboard

- Paper: committed/reserved/remaining allocation, sector usage, coverage, entry
  reasons, check timestamps, next check, expiry, quote/spread/price evidence.
- Research: observation-only comparisons and rejected-candidate cohorts.
- Signals: underlying metric coverage, input warnings/blockers and price anomalies.
- Human-readable reasons with technical evidence available separately; timestamps
  use the established long US format in Eastern Time.

## Explicit limitations

No verified earnings calendar is connected. Known recorded earnings events within
24 hours block an entry; missing events remain **unknown**, and the default policy
does not block the entire universe for missing calendar coverage. This must not be
presented as comprehensive earnings screening. Sector-relative valuations and
quarterly/TTM financial trends are not enabled: comparable, point-in-time coverage
needs validation first. The filing-age check does not establish fiscal-period
freshness. IEX volume remains single-exchange volume; the existing liquidity risk
rule is unchanged. No financial-performance improvement is claimed.

## Validation and deployment

Local worker suite: 245 tests; dashboard suite: 42 tests. Includes cross-version
limits, shared Unknown bucket, concurrent last-capacity reservations, highest-score
allocation, expiry/outage behavior, scheduled-context deferral, broker idempotency,
quote/cash/earnings blocks, immutable policy configuration and rejected outcomes.
Linux tests/build and desktop/mobile browser checks are also run on the staged
release. Installer SHA-checks tested artifacts, waits for running jobs, refuses to
strand queued jobs/unreconciled entries, backs up source/build/worker/environment,
applies additive migration 013, selects paper-v2, checks HTTP endpoints and restores
timers. Failure restores prior code and selected environment; additive tables and
observations remain. No full 24 GiB database copy is made for this additive release.
