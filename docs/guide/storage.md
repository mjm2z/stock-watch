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
| Stock history | Provider/cache isolation by symbol, range, raw/adjusted basis, custom dates and resolution; 6,000 intraday bars / 12,000 daily stock bars maximum |

Activity IDs identify recorded transitions, not hypothetical market events.
Existing rows do not produce retrospective insert events during migration.
Original fills and audit tables remain the source for pre-release evidence.
Activity records preserve order identifiers and attribution; unavailable input
values or late fee information are not filled in with assumptions.

Back up the main and auxiliary databases and artifact directories before
migration. The reviewed installer already includes sibling artifact directories
in recovery inputs. Never copy an active SQLite database with a plain file copy
and assume the WAL was captured consistently.

## Storage maintenance

The September 30 audit found roughly 232 GiB of release database copies, 75 GiB
of scheduled/abandoned backups, 44 GiB of live application data, and numerous
old runtime/staging trees. Live Coinbase and manual-paper databases were only
kilobytes/megabytes; they did not explain the main database's size. Old copies
and an abandoned 41 GB backup were cleaned first. Host free space rose from
about 78 GiB to 279 GiB, with all four core services active. The original cleanup
reported 60,472,094,720 bytes reclaimed; the later disk measurement is consistent
with removing four older recovery databases totaling 155,874,992,128 bytes.

The following prevention changes were installed with `fb6c33a` on October 1
at 21:12 Eastern. Compaction reduced 48,012,939,264 bytes to 3,842,609,152 bytes,
reclaiming 44,170,330,112 bytes while preserving 11,569 observations and 681
unique content bodies. The installed receipt and all four active core services
were verified afterward. A fresh recovery copy is retained at
`/var/backups/stock-watch-releases/20261001T200907Z`. The cleanup timer is enabled.
Migration **023_company_fact_storage** separates SEC CompanyFacts observations
from their JSON bodies. Every observation retains its original ID, capture time,
instrument, provider and ingestion reference. Identical bodies share a SHA-256
content record. The historical `company_fact_documents` read interface becomes
a view. Hash/body conflicts abort the migration transaction; they are never
silently merged. Application inserts use the underlying tables for durable IDs.
Historical dataset assembly reads only the latest eligible body per instrument.
No trading ledgers, historical results, qualification decisions or Bitcoin
calculations are rewritten.

A bounded sample contained 14 identical bodies: 71.7 MB stored versus 5.1 MB
unique. This demonstrates duplication, not a database-wide savings estimate.
The live database had zero free pages, so VACUUM alone would not reclaim that
space. Deduplication frees pages; offline VACUUM then returns them to the disk.

The reviewed installer makes and verifies a fresh full recovery backup, drains
StockWatch writers, applies the transaction, compacts, checks SQLite integrity
and foreign keys, and verifies observation/content counts before resuming.
It reserves space for the backup plus twice the original database size and
5 GiB for compaction (at least the usual 20 GiB deployment reserve). Reading and
rebuilding a roughly 41 GiB database on this disk can take hours. The app and
application-managed trading instructions are unavailable during maintenance;
broker-held orders remain at Alpaca. Do not start a second installer.
Migration and compaction log progress at approximately 30-second intervals
while SQLite executes; kernel I/O can delay progress output.

Monitor from the staged release directory using:

```sh
python3 deploy/monitor-release.py --unit stock-watch-release-<revision-prefix>.service --watch
```

Use the actual unit name printed by the installer launcher. A stopped unit alone
does not prove success: check exit status, installed receipt and service health.
If migration succeeds but compaction fails, leave services stopped and rerun the
reviewed installer with `--compact-database`; it forces another verified backup
and retries compaction. VACUUM is transactional, but it does not roll back the
already committed schema migration. A rollback to older application code needs
its matching pre-migration database and retained artifacts/configuration, not a
code-only switch: older writers do not understand the new observation tables.

The installed daily `stock-watch-storage-cleanup.timer` will run at 03:30 UTC
plus up to ten minutes of jitter, without missed-run catch-up. Its helper keeps:

- The current runtime, two newest rollback runtimes and receipt-linked rollback.
- Matching staged revisions plus the two newest staging directories.
- The two newest verified full release database copies. Older release metadata,
  protected configuration, auxiliary databases and artifacts remain untouched.
- Completed scheduled backups under their existing backup retention policy.

It deletes only recognized older candidates and abandoned temporary backups more
than six hours old when a completed backup exists. Release/backup locks, active
process checks, symlink rejection and file identity checks guard removal. It
leaves unrelated applications and the separate migration archive alone. Inspect
without mutation with `cleanup-storage.py --automatic --recovery-backups`;
`--apply` is required to delete. The helper must run as root on a1347-m.
Scheduled backup SIGTERM handling now closes SQLite and removes its incomplete
temporary files while preserving completed backups; SIGKILL leftovers are handled
by later cleanup. Root-only verification markers describe past recovery checks;
actual database file presence is required before a copy counts toward retention.

## Display cache budgets (UI release, pending deployment)

The shared browser chart LRU holds at most 32 entries / 16 MiB of serialized JSON;
stock history's server LRU holds at most 64 MiB with a one-minute TTL. Crypto chart
response cache entries retain at most two days / 64 MiB, with expired and over-budget
payloads evicted on reads and writes. These are payload budgets, not JavaScript heap
or allocated SQLite file measurements. In-flight requests are coalesced and bounded.
Research history, immutable datasets and order evidence do not use these eviction
rules. Migration 024 adds the scan/ranking index used for paginated Signals reads.
The background Signals reader has two workers, up to 16 outstanding distinct requests,
a 15-second execution deadline and an 8 MiB/64-entry result cache lasting 15 seconds.
