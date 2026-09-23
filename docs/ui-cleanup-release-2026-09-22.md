# UI cleanup — September 22, 2026

## Delivered behavior

- Overview and Paper prioritize actual paper performance versus matched SPY. Valuation timestamps and contribution basis are explicit; unvalidated live drawdown is labeled unavailable.
- Paper separates current filled lots and pending reservations, shows the next exit submission target, and collapses allocation history and the browser-local manual sandbox.
- Signals retain desktop tables and become labeled mobile records. Filters have accessible labels and choices; exact-scan links, Eastern date boundaries, total counts, correct pagination, and explicit 500-row export truncation are supported.
- Equity history uses the newest 1,000 snapshots. Dates, dollar values, contributions, accessible snapshot inspection, and missing-SPY gaps are visible.
- Execution warnings are consolidated without inferring recovery. Operations groups retries by recorded job ID and keeps raw evidence expandable; full broker balances are distinguished from the strategy allocation cap.
- Research puts search, watchlist, and journal before experiments. Experiment comparisons filter by strategy and horizon. Journal failures preserve drafts; overdue original review dates and load failures are visible. Historical browser-watchlist import is secondary.
- Search has a button and keyboard listbox relationships; late search and chart responses cannot replace newer results. Polling reads have timeouts and preserve previously loaded data with warnings.
- Navigation has visible mobile labels and active-page semantics. A skip link, page loading/error states, chart overlay availability, contextual back links, and manual saved-results refresh are included.

## Compatibility

Only web source and the web production build are installed. No worker changes, migrations, strategy controls, order submissions, timer changes, or exit-policy activation occur in this installer.

Existing dashboard response fields are retained. Signals add `meta` (matching observations and distinct-company totals, strategy/reason choices, generation time, exact scan scope), optional `scanRunId`, and optional `timezone=America/New_York`. Without the timezone parameter, existing API date filtering remains UTC. CSV adds `X-Total-Count` and `X-Export-Truncated` headers.

Portfolio adds snapshot/generation timestamps, a performance-availability flag, pending-lot count, and reserved notional. The UI hides valuation-derived figures when a snapshot is unavailable. Equity remains a contribution-sensitive dollar chart, not a validated cash-flow-adjusted return or drawdown series.

## Verification

- 54 JavaScript/TypeScript tests pass locally and on Linux. Added coverage includes newest-snapshot rollover, missing valuation/benchmark data, pending reservations, exact-scan scope, Eastern DST boundaries, benchmark path gaps, early-close display, qualified-but-blocked signals, experiment filters, keyboard search, late-response rejection, and draft preservation after failed saves.
- Local and Linux production builds and type checks pass. The staged SHA-256 manifest verifies 449 release files. Existing console warnings in the AI integration remain unrelated.
- Browser checks exercised Overview, Signals, Paper, Research, Operations, Backtests, and stock details at 390, 768, and 1440 pixels using an isolated migrated SQLite fixture. Expanded sections also fit 320, 640, and 720-pixel widths; 720 pixels covers the reflow width of a 1440-pixel display at 200% zoom. Native browser zoom itself was not automated.
- No page-wide horizontal overflow was observed after correcting the intermediate navigation breakpoint and the expanded backtest card. Primary form controls have accessible names; keyboard Tab reaches the skip link. Populated research/backtest data were included; no production research writes were made.
- Linux staged-build smoke checks returned HTTP 200 for all seven reviewed routes; exact-scan/Eastern-date result counts and CSV truncation headers passed against synthetic data.
- Testing caught and fixed SQLite null-prototype rows crossing a server/client boundary. This now has a regression assertion.

Temporary review artifacts: `/tmp/stockwatch-ui-review/` on the development Mac.

## Installation

Staging: `/home/mjm2z/stock-watch-ui-20260922` on a1347-j. The release uses the existing locked Linux dependencies and a Linux production build, with SHA-256 verification before installation.

Run on a1347-j:

```sh
sudo bash /home/mjm2z/stock-watch-ui-20260922/deploy/install-ui-root.sh
```

The installer runs independently of SSH as `stock-watch-ui-install.service`, backs up the prior web source/build, creates the required writable Next cache directory, and restores the previous website if verification fails. It restarts only `stock-watch-web.service`.

```sh
journalctl -u stock-watch-ui-install --no-pager -n 40
```

Root installation requires the host administrator password; `sudo -n` is unavailable. Until that command completes, the new UI is staged, not live. After installation, check the main pages, portfolio snapshot time, scheduled exit targets, and unchanged worker/exits timer state. The news fix still needs its first post-install scheduled scan; UI warning cleanup does not establish scan recovery.

## Production installation verified

The installer completed successfully September 22 at 4:27:33 PM Eastern (exit 0).
Startup connection/time-out retries recovered; no rollback was required.
Rollback files: `/var/backups/home-ops-code/stock-watch-ui-20260922T202647Z`.
The live web service, worker, dispatcher, maintenance, and exit timers are active.

The 4:15 PM Eastern close scan also succeeded after the news-revision fix, with
503 companies in the recorded scan diagnostics and a new successful scan bundle.
Execution status now reports `ready` with no issues, and broker positions match.
This verifies the first post-fix scheduled scan; it does not yet verify an actual
managed exit fill or establish improved trading returns.
