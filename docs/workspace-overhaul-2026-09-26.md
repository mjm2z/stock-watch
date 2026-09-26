# StockWatch workspace overhaul

The interface now shares the local app family's charcoal/light palette, persistent sidebar,
asset switch, aligned headings, responsive drawer, and centralized operator access. The
canonical Crypto view is `/crypto`; existing `/bitcoin` links and stored `bitcoin` asset values
remain compatible. SVG, multi-size ICO, and Apple icons accompany the StockWatch name.

## Research and execution

- Crypto history has day/week/month/quarter/six-month/year/all/custom ranges, line/candlestick
  and volume controls, crosshair values, zoom/pan/reset, and an accessible data table. Actual
  source coverage, collection time, partial responses, and gaps are explicit. Worker-collected
  chart caches are independent of qualification data. Cache refresh preserves the visible range.
- Visual systems support Stocks and Crypto, nested ALL/ANY conditions, OHLC/volume, SMA/EMA/RSI,
  average volume, prior highs/lows, comparisons and crossover events. Rules are bounded and
  versioned. Immutable original strategy hashes remain unchanged.
- Drafts survive session expiry in browser session storage and can be saved to the database.
  Publishing freezes the submitted document before queueing. Versions support duplication,
  subsequent revisions, history and archive/restore. Paper-authorized versions cannot be hidden
  by archiving. Archiving changes presentation, never execution authority.
- Backtesting uses durable, cancelable jobs, selected intervals/timeframes and execution-cost
  stress. Compare up to four of the latest 20 runs using equity/drawdown charts, benchmarks,
  modeled fills and retained limitations. Display samples are bounded; stored evidence is intact.
- Paper start requires explicit confirmation of the exact version. Funding and qualification
  alone do not grant initial entry authority. Existing orders retain their authority during
  migration. Runtime qualification, reconciliation and account risk checks still gate orders.

## Material constraints and findings

Historical bar execution is approximate and does not count as forward-observed evidence.
Stock datasets use captured raw bars and current membership/sector metadata: corporate actions,
survivorship bias and limited coverage remain material. No backtest should be read as a forecast.
Stock visual exits evaluate completed daily bars and execute in the existing stock exit window;
these are not intraday guaranteed stops. Crypto exits use available quotes. Both remain subject
to liquidity, broker availability and the existing account-wide caps.

Historical collection is bounded at 60,000 bars per manual run. Shorten intraday intervals when
necessary. Research jobs share the existing serialized research worker; a long job can delay the
first chart collection. Chart history errors are visible; unavailable prices are never fabricated.

The release enables collection-only Bitcoin data. **Existing execution timer states are preserved.**
A host administrator must enable the appropriate execution worker before an operator can fund or
activate a new paper system. This is shown in the paper workflow; deployment does not authorize
any strategy. Existing disabled execution workers are intentionally left disabled.

## Verification

Local verification: 317 worker tests, 68 frontend/store tests, four release-guard tests,
TypeScript checking and Next production build. Additional browser checks covered nine primary
screens at widths 390/768/1280/1440, no horizontal overflow, aligned Stocks/Crypto headings,
page titles/icons, operator login, draft publishing, preselected backtest version, chart controls,
light-theme persistence, mobile navigation and Escape. Interactive chart browser checks used
explicit fixture data in an isolated database, not production market data.

Migration tests preserve existing versions/orders byte-for-byte and distinguish pre-existing
order authority from never-started funding. Installer checks ledger counts and authority records
before/after additive migrations. Production installation and real-provider history still need
post-install verification; local browser results do not establish deployed readiness.

## Release and recovery

Install only the checksum-reviewed Linux build with `deploy/install-reviewed-release.py`.
It drains writers, stops the web app, creates and quick-checks a fresh database backup, retains
configuration and the full previous runtime, applies additive migrations and compares history and
trading authority. It restores previously enabled timers; no strategy is activated.

Keep the recovery directory and previous runtime for at least 30 days and through a complete
US trading session plus continuous Crypto observation. If readiness fails, keep writers stopped,
inspect the installer recovery path, and restore the previous runtime with compatible data before
restarting only the recorded timer set. Do not overwrite a database that has received new writes
without reconciling those writes and broker-owned orders first.
