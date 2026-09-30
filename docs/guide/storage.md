# Storage and provenance

[Application guide](../../README.md)

The main SQLite database retains existing automated ledgers, immutable system
versions, datasets and research history. Migration `022_research_inspection.sql`
is additive: optimistic draft revisions, research-only snapshots, previews,
experiment plans, attempts, reviews, interval-access records and future activity.
It does not update old fills or qualification records.

`manual-paper.db` remains separate. Its startup migration adds a revision counter,
state-change triggers, a prospective activity table and minute allocation valuations.
Valuations retain status/unavailable reasons, budgets, cash, marked equity and
observed drawdown; the latest 600 records are returned for bounded display. Changes to account,
draft, instruction, protective-plan and fee state advance the revision; routine
health writes do not. A confirmation fails if relevant state changed while broker
validation was in progress. Existing instruction columns and default limit
requests remain compatible. Market notional lives in the durable broker request;
zero stored requested quantity is not a predicted market-buy fill quantity.

`market-data.db` holds bounded feed diagnostics and minute aggregates, rather
than adding every tick to the large application database. Seven days of
diagnostics and 90 days of minute aggregates follow the existing retention
policy. Observations used for an order remain in its durable audit evidence.

Research datasets and complete preview results are content-addressed files in
`<main-database>.systems-data`. The worker verifies dataset bytes against their
recorded hash, freezes the engine identity and calculates metrics over complete
curves. Result artifacts use `<sha256>.preview.json`; the main DB retains bounded
curves (600 points), fills (200) and trade summaries (200). Downloads verify the
hash and size before returning evidence. Cached previews retain original creation
time and artifact identity and record the new inspection separately.

The runtime I/O hotfix changes feed retention only: tick publication remains
immediate, while diagnostic minute aggregates are combined in memory and flushed
at most once per second in a separate worker thread. One batch may be in flight;
the pending map is bounded to 120 minute buckets. OHLC and observation counts are
preserved across successful batches. The diagnostics keep seven days and minute
aggregates keep 90 days. This adds no polling or debounce to the live display.

Unflushed diagnostic observations can be lost on process failure. A stalled disk
can overflow the bounded diagnostic buffer; dropped buckets and persistence errors
are exposed in the snapshot's `retention` status and make collector health fail.
An uncertain worker failure is not blindly retried, avoiding double-counted
observations; restart the collector after addressing the storage problem. Live
price freshness is still evaluated independently. These diagnostic aggregates
are not order/audit records, and no broker or trading-ledger durability is relaxed.

| Read API | Bounds and meaning |
| --- | --- |
| `/api/inspection?asset=stocks&symbol=SPY&scope=manual` | Current raw-price levels, explicit owner/source/as-of; bounded ledger rows |
| `/api/activity?asset=bitcoin&scope=manual&before=…` | Cursor pages, default 50, maximum 200; filters are SQL-bound parameters |
| `/api/systems/lab?asset=bitcoin` | At most 30 previews, 50 experiments, 100 snapshot metadata rows |
| `/api/systems/lab/artifact?sha=…` | Known retained preview hash only; no caller-supplied filesystem path |
| Stock history | Provider/cache isolation by symbol, range, raw/adjusted basis, custom dates and resolution; 6,000 bars maximum |

Activity IDs identify recorded transitions, not hypothetical market events.
Existing rows do not produce retrospective insert events during migration.
Original fills and audit tables remain the source for pre-release evidence.
Activity records preserve order identifiers and attribution; unavailable input
values or late fee information are not filled in with assumptions.

Back up the main and auxiliary databases and artifact directories before
migration. The reviewed installer already includes sibling artifact directories
in recovery inputs. Never copy an active SQLite database with a plain file copy
and assume the WAL was captured consistently.
