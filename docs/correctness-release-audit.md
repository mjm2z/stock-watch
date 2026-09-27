# Correctness release audit

Baseline: 8467b6f. This record distinguishes implementation evidence from hypotheses.

| Priority | Evidence / status | Change and acceptance | Dependency |
|---|---|---|---|
| P0 | Collector explicitly uses IEX; legacy market-bar identity lacks feed | Preserve legacy inputs; separate feed observations and provenance; cross-feed writes cannot overwrite | Historical SIP entitlement probe |
| P0 | Fill-cohort capital is accumulated entry cost, not broker deposits | Canonical scope/method metadata; account return index only with complete flows and valuations; deposit neutrality tests | Sufficient account observations |
| P0 | SEC CompanyFacts captured vintages already selected at cutoff; annual extraction guards nonpositive equity | Retain baseline; add conservative availability and fiscal-period/capability reporting under a new feature version | Acceptance timestamps where available |
| P0 | Existing stock datasets disclose current membership and unverified actions | Explicit capability report; no favorable qualification from unsupported coverage | Historical membership/actions |
| P0 | 503 companies produce 2,012 horizon assessments; latest diagnostic has multiple blockers | Reconciled scan funnel, primary and secondary reasons, execution counts | Stored assessments and checks |
| P0 | Missing discovery heartbeat produces 503 before first scheduled run | Verify systemd schedule before allowing not-yet-due; failed/disabled/stale remain explicit | Read-only systemd status |
| P1 | Standard evaluation needs 39 months for first fold and holdout | History preflight and lineage-wide holdout registry | Next release |
| P1 | Discovery windows/profiles overlap and flat-start | Continuous replay and full return evidence; no new authority from diagnostics | Next release |
| UI | Existing scanner and visual systems intentionally coexist | Show owner/method; never invent missing visual backtests | Existing IDs |

Existing authority: Bitcoin experimental historical policy remains enabled at its approved limits. New research semantics require a new immutable protocol/version and stay in shadow mode. Both account owners and existing exits must survive rollout. Existing history is never relabeled as newly verified coverage.

## Release 1 implementation boundary

Implemented locally: additive migration 020; feed-isolated storage; scan diagnostics and bounded backfill; conservative shadow TTM construction; dataset capability reporting; canonical account measurements and recent return-index charts; corrected cohort labels; schedule-aware discovery readiness; recovery coverage for both databases and retained artifacts.

Verified non-bugs: 2,012 represents horizon assessments, not 2,012 stocks. Scanner-owned lots do not require a visual-system run. Quote/candle values are separate products. No scoring threshold was reduced to generate activity.

Important remaining work:

- The user-run read-only historical probe returned five AAPL daily bars for IEX and SIP, with last-session volumes 788,509 and 24,871,878. That request succeeded; real-time entitlement is not established. The production scanner still uses IEX, including its existing absolute-volume thresholds; their consolidated-market interpretation remains a known limitation pending a separately versioned comparison.
- No historical membership, delisting, corporate-action, or missing-session evidence is invented. Dataset reports surface retained claims and unavailable prerequisites. This change does not implement a corporate-action replay engine.
- Fundamentals v2 is a prospective shadow report. It does not replace published annual features, reconstruct missing filing acceptance times, or backfill all historical CompanyFacts.
- Account marks start prospectively. Missing flow-event valuations invalidate the full-period result; there is no automatic restart of the measurement baseline. Broker cash/equity remains visible. Funding-matched benchmarks and sleeve-level unitization remain unavailable. The legacy matched-entry-cost SPY comparison is a separate cohort proxy.
- Continuous research replay, complete trial-return matrices, DSR/PBO, history preflight, holdout tracking, execution attribution, aggregate exposure controls, proposal experiments, and broad UI consolidation belong to later stages. They are not described as delivered by Release 1.

## Verification and rollout

Local checks: 360 Python tests plus 25 deployment tests; 79 web tests; TypeScript and production build passed. Existing lint warnings remain in app/api/analyze/route.ts, components/Navigation.tsx, and lib/claude.ts (see build output for exact locations). Browser smoke used isolated non-sensitive fixtures at 390px and 1440px on Overview, Paper trading, Operations, and Crypto: all HTTP 200, no horizontal overflow, no JavaScript exceptions. Performance/scans/capabilities APIs returned 200, invalid asset 400, and missing worker readiness 503. Screenshots were inspected locally; these are fixtures, not production results.

Historical pre-install baseline was 8467b6f. Superseded by the installed-state checkpoint below. Migration 020 used the full backup path; later unchanged-schema releases retain the fast code-only path.

## Addendum reconciliation and installed checkpoint

Checkpoint: 2026-09-27 20:21–20:33 UTC. Local starting revision `4b2d267850f283f01c8b9412154047588c0b840e`, clean tree; locally recorded origin/main equal. Historical anchors 1163bc2 and 9fbc88b are ancestors, but preservation evidence below comes from code/tests as well. Single integration owner: current StockWatch agent. The other agent remains paused from shared-tree writes.

Installed receipt: `62bcffd3090fdb4ccebf08ebc9c9ec84076528e8`, installed 20:16 UTC, database-changing mode with 020 pending at installation and `database_backup_created=true`. Journal records 020 applied and release verified, successful exit. Recovery `/var/backups/stock-watch-releases/20260927T144107Z`; previous runtime `/opt/stock-watch.before-20260927T144107Z`. This is receipt/journal evidence, not an independent re-read of the protected ledger/recovery contents. Closeout tooling has no application-code changes and does not trigger another installation.

| Item | Source/history | Current code/test evidence | Status | Owner | Release/follow-up | Blocker |
|---|---|---|---|---|---|---|
| Decision cadence and independent calendar holding | 1163bc2 | systems/timeframes.py; test_bitcoin_automation calendar/month-boundary tests | preserved | Integration | Existing runtime | None |
| 100 scenarios, chronology, unique trades, corrections/cache | 1163bc2 | systems/evaluation.py, automation_replay.py; test_bitcoin_automation unique-trade, revision/cache tests | preserved | Integration | Existing runtime | Not independent observations |
| Strict forward versus experimental historical authority | 017/019 | systems/coordinator.py, automatic_paper.py; test_bitcoin_automation and test_research_control | preserved | Integration | Existing runtime | No new policy authorized |
| Old $300 versus experimental policy caps | Original versus 019 | automatic_paper.py reads current policy/cash; manual allocations skipped; fixture protects both owners | intentionally superseded | Integration | Existing versioned policies | Caps are not deposits |
| Expiry, duplicate entry and exit continuity | 9fbc88b | test_research_control stale/pause tests; test_bitcoin_automation expiry/outage, fees and concurrent reservation tests | preserved | Integration | Existing runtime | Live GET checks completed; full post-install fill reconciliation not asserted |
| Stock lots, fill values, hashes, reservations and authority upgrade | 020 closeout | Expanded installer PRESERVED_TABLES; populated pre-020 upgrade test and same-count mutation tests | already fixed | Integration | Future installer, no runtime redeploy | No new migration |
| Provenance, conservative fundamentals, account measurements, diagnostics | 62bcffd | 020 and test_correctness/test_scan_executor; prior build/browser verification | already fixed | Integration | Installed Release 1 | Documented data limitations remain |
| Migration classification and recovery | 8467b6f/62bcffd | Pending/edited migration and auxiliary DB/artifact tests; protected report confirms 020 and recorded recovery verification | already fixed | Integration | Installed installer plus closeout checks | No repeated full integrity scan |
| App availability versus worker readiness | Live inspection | /api/health ok; /api/systems/health blocked, six stock trials | deferred | Integration | Explicit operational limitation | Raw bars/sector/calendar prerequisites |
| Exact stock missing-input diagnosis | Exporter versus scanner | Protected report: raw absent, adjusted present; universe/calendar/sectors present; exportable rows absent | deferred | Integration | Separate data-prerequisite follow-up | Requires raw collection and separate corporate-action coverage; no substitution |
| Distinct broker identities and Bitcoin flatness | Protected GET report | Distinct actual accounts; stock local identity matches; BTC no positions/orders; no open stock orders | preserved | Integration | Verified at 20:40 UTC | Snapshot only |
| Fresh stock quantity/cash/fill reconciliation | Protected ledger read | Latest stored match is September 25 21:15 UTC; seven open lots, two broker positions | unverified | Integration | Next scheduled reconciliation / focused inspection | GET counts do not establish full reconciliation |
| Historical SIP request | User-run probe output | Five bars each; same last session, differing volume | already fixed | Integration | Documented capability only | No automatic feed change |
| Trial/holdout accounting and history planning | Original P1 | Audit still lists as unfinished | deferred | Paused agent after handoff | Read-only preflight design assignment | Closeout base commit |

### Operational observations and remaining verification

Bitcoin automation, Bitcoin data, discovery and stock-exit timers are active. Legacy Bitcoin trading and visual stock execution timers remain disabled. On a1347-m at 20:33 UTC the latest exit and automation service executions succeeded (20:33:00 and 20:33:06 UTC). No execution-capable command was invoked for inspection. Exit service success on a Sunday establishes execution of the scheduled handler, not an actual broker exit fill.

Six Bitcoin trials completed 100 scenarios each; zero authorizations/allocations were exposed by the API. Six stock trials were blocked with `Captured daily bars, sectors, and market calendar are required`. This is a prerequisite warning, not evidence of broken Bitcoin replay. Keep it visible; do not lower qualification thresholds, fabricate raw prices, or rerun expensive discovery simply to change a status.

Follow-up GET inspection at approximately 20:38 UTC explains Bitcoin non-qualification: all six summaries have `passed=false`, scenario pass rates 15–30% versus the 80% policy requirement, and 4–21 unique closed trades versus 30 required, plus nonpositive median base returns and cost-profile failures. These are scenario results, not live win rates. No funding or forced order is an appropriate response.

The unprivileged closeout report ran on the host at 20:36 UTC: 133 selected installed files matched the reviewed manifest, with no mismatches. Database and recovery reads explicitly reported unavailable due to permissions; no broker request was made. The tested report is staged at `/home/mjm2z/stock-watch-closeout-20260927/closeout-report.py` for the remaining protected read-only inspection.

The root-only database, recovery metadata and protected environment cannot be read by the SSH user; `sudo -n true` returned `a password is required`. The operator subsequently ran `deploy/closeout-report.py` successfully at 20:40 UTC and supplied its JSON output, reviewed below. It provides per-section availability and deliberately does not print an overall success certification. Hash inspection is scoped to worker/migrations/lib/installer/build-ID files, not the entire installed build. HomeOps external readiness registration remains a separate monitoring follow-up; source availability alone does not prove monitoring is configured.

### Protected report reviewed: 2026-09-27 20:40:56 UTC

The operator-run unit `run-u227479.service` exited successfully in 1.476 seconds. Its report confirms:

- Migration ledger contains 001 through 020. `pending_migrations` in the receipt describes the **pre-install deployment plan**, not currently pending migrations.
- Recovery metadata records successful verification; the main database file is 38,974,132,224 bytes and Bitcoin-history file 40,960 bytes; artifact manifest contains 11,102 entries. This inspection checks recorded verification and file presence, not a second full integrity/hash scan of backups/artifacts.
- All 133 scoped installed-file hashes match. Required timers remain active; legacy Bitcoin trading and visual stock execution remain disabled.
- Stock data prerequisite diagnosis is now confirmed: no raw daily bars; adjusted bars, universe, calendar and sectors are present. No exportable raw rows. Collecting raw bars alone would not satisfy the separate corporate-action/history qualification requirements.
- All six Bitcoin research candidates completed but failed qualification. Policy remains enabled with threshold 0.8, pool cap 1000, sleeve cap 200 and entry cap 100. No allocations, orders, qualifications or authorizations exist locally. Limits were not increased and no order was forced.
- GET-only broker observations establish distinct actual account identities, stock identity matching its local record, no open orders in either account, and zero Bitcoin positions. Bitcoin credentials work; local registration has not occurred because no candidate passed. Stock has two broker positions and seven open lots, plus one closed lot; these are different aggregation levels, not evidence by themselves of a discrepancy.
- Latest stored stock reconciliation is `matched` at **2026-09-25T21:15:01Z**, before this deployment. Sunday successful exit ticks do not refresh that full reconciliation. No new post-install fill/fee or quantity/cash reconciliation is claimed. Continue existing scheduling and retain that explicit verification limit.

Closeout tooling/documentation and protected inspection are complete. Remaining operational limitations are stock raw-data prerequisites and a fresh full stock reconciliation; broader research changes and HomeOps monitoring remain separately scoped follow-ups. No additional application installation is required for this documentation checkpoint.

Run the staged report from the Mac (the sudo password is entered on a1347-m; no backup or application restart):

```sh
ssh -t a1347-m "sudo systemd-run --wait --pipe --collect -p EnvironmentFile=/etc/stock-watch/stock-watch.env -p EnvironmentFile=/etc/stock-watch/systems.env /usr/bin/python3.12 /home/mjm2z/stock-watch-closeout-20260927/closeout-report.py --manifest /home/mjm2z/stock-watch-releases/62bcffd/reviewed-release.json --broker-readonly"
```

Review the resulting schema, recovery, input presence, broker identity/positions and reconciliation timestamp sections. Any unavailable section remains unverified; a successful report process is not a clean bill of health. Do not paste environment files or credentials into the handoff.

Launch correction: the first operator command combined both environment paths into one `EnvironmentFile` property. Unit `run-u227376.service` failed before Python started with `Failed to load environment files: No such file or directory` (result `resources`); the report did not execute. Use one property per file as above. This exact repeated-property form was verified on a1347-m in an isolated user service with two temporary non-sensitive environment files; both values loaded and the test exited zero. No application service was changed.

### Closeout verification (2026-09-27)

- `PYTHONPATH=worker/src /opt/homebrew/bin/python3.12 -m unittest discover -s worker/tests`: 361 passed, including the populated pre-020 migration fixture and the existing five-system/500-scenario resource fixture (about 1.04 seconds; maximum fixture stock write 0.0015 seconds). This is a local resource regression, not profitability evidence.
- `/opt/homebrew/bin/python3.12 -m unittest discover -s deploy -p 'test_*.py'`: 32 passed, including missing-DB noncreation, read-only/redacted report behavior, blocked readiness, unregistered broker-position reporting and comparing actual broker identities rather than only keys.
- `npm test -- --runInBand`: 79 passed across 19 suites.
- `npm run type-check` and `npm run lint`: passed; the same three pre-existing warnings remain.
- `npm run build`: passed. Existing lint warnings, Node experimental SQLite notice and stale Browserslist data notice remain. No new browser smoke is required: this closeout changes no UI, API or application runtime behavior; previous fixture smoke remains historical evidence.

One intermediate test exposed that the installer snapshot helper assumed tuple rows. It now serializes `tuple(row)` and works with both default SQLite rows and sqlite3.Row; the full suite passed afterward.

README changes and this audit are part of the closeout commit. For exact base revision and permitted work for the paused agent, see [history-preflight follow-up](history-preflight-followup.md). Continuous replay, trial/holdout registry, DSR/PBO, execution attribution, consolidated-feed strategy validation, aggregate risk/sizing experiments, broad UI consolidation and backup storage/growth profiling are not delivered by this closeout.

## Stock input follow-up — implementation checkpoint

Base `0c897e8`; single integration owner continues. Confirmed live blocker was absent raw bars, not absent adjusted scanner history. The existing historical collector already accepts raw internally; its CLI previously exposed only feed and silently used its adjusted default. Added `--adjustment raw|all` with unchanged `all` default, preserving separate ingestion identities and feed provenance. Tests show adjusted rows remain byte-for-byte equal, identical raw requests reuse completed ingestion, and SIP cannot overwrite IEX compatibility rows.

Added a shared SQL prerequisite query packaged into the Python wheel and read by Next.js. The new read-only `/api/systems/preflight` reports basic source/calendar/sector/date coverage and ambiguity, and the Stocks backtest form exposes the result before submission. New requests are checked before writing a job; the worker checks again. Idempotent retries are preserved. This is input-presence preflight, not the full warmup/fold/holdout planner in the paused agent's assignment. Partial coverage is disclosed; corporate-action and historical membership limitations remain. No published strategy hashes, scenario semantics, budgets, ownership or execution timers changed.

Validation: 366 Python, 32 deployment, 86 web tests passed; type-check, lint and production build passed. The intermediate TypeScript return-shape inference failure was corrected with explicit SQL result types before the passing build. Isolated browser smoke on `/backtesting?asset=stocks` at 390px/1440px passed: blockers shown, submit disabled, no overflow or browser exceptions; Crypto has no stock prerequisite panel. Screenshot inspected locally. Sandbox initially blocked loopback/Chrome; the same checks passed with approved local execution. Fixture results are not production data.

Deployment boundary: no new migration and no initialization-file changes, so the current 020 host should use reviewed code-only installation. No production raw collection has been performed. Raw IEX collection, requested calendar coverage, and a fresh scheduled stock broker reconciliation remain operational follow-ups. Collecting raw bars does not resolve the independent corporate-action qualification blocker. The Linux artifact build/verification and exact staged revision are supplied at handoff; the previous installed app remains `62bcffd` until the operator installs the reviewed package.
