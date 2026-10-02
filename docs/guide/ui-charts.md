# UI, chart inspection and activity

[Application guide](../../README.md)

The sidebar retains Stocks/Crypto context. Paper trading leads to the manual
allocation workspace with visible links to automated portfolios and scanner
paper trades. Paper trading follows Overview in desktop/mobile navigation. Activity
uses an ordered-list icon; Signals uses a radar icon. Green primary accents, links
and focus rings distinguish StockWatch from other local applications; surfaces stay
neutral and profit/loss colors retain their meaning. Forms use labelled inputs, keyboard-operable controls, bounded
responsive tables, explicit loading/error/empty states and preview/confirmation.
Read-only users can inspect records but cannot submit mutations.

Stocks Overview starts with SPY and supports **five total symbols**. Search by
company name or ticker; selected symbols form a horizontal removable legend.
Only symbol choices persist in browser storage. One symbol supports candles,
hollow candles, OHLC bars and lines; multiple symbols use lines with an explicit
$/% scale. Comparison starts at a shared observation and keeps that baseline
fixed while older bars load. Missing prices are not forward-filled.

Presets choose resolution automatically. Zoom/pan expansion loads bounded adjacent
history with a small chart-corner status, preserves the viewport, and switches to
coarser bars when needed. Custom calendar dates remain explicit boundaries. Reset
view restores the selected preset/date interval. History ends and retryable errors
are distinct states. Overview charts use adjusted stocks and separate Alpaca
Crypto candles; Coinbase's live badge is not a candle source.

The overview has no ownership selector, simulated layers or accessible data table.
Dedicated inspection views retain those interfaces. Existing Lightweight Charts 5
provides pan/zoom, attribution and cleanup. Current overlay price lines update
without rebuilding the base chart; no drag-to-trade behavior is implemented.

Crypto's live badge aligns with the chart's right edge, with BTC/USD and status
above a larger left-aligned price. Overview headers use compact spacing. Crypto
research/setup promotions are absent from Overview but remain reachable through
Systems, Backtesting and Paper trading. Network conditions presents freshness and
three compact metrics rather than a large promotional card.

Layer controls select presentation only. Scope is explicit: Manual, Automated,
or scanner. Limit/stop/trigger prices, current position basis when reconciled,
local protective thresholds and owner information are inspectable. Market orders
show pending state without a fabricated execution price. Current overlays include
source/as-of/valid-from evidence; they are not historical assertions. Stock raw
broker layers are disabled over adjusted history.

Activity markers group events into visible chart bars. IDs deduplicate retries;
exact event times and original evidence remain in a linked inspector. The activity
view supports cursor paging and asset/scope/symbol/account/owner/type/status/date
filters. Original older ledgers remain accessible through existing portfolio
views; new transition history starts prospectively.

System selection exposes immutable configuration identity, decision timeframe and
recorded state where available. Missing historical rule series are explicitly
unavailable. A separately selected completed research preview can show simulated
rule values and fills, always marked PREVIEW. Higher-timeframe values are labelled
with their completed decision bar; they are not painted into earlier intraday
history as if already known. Volume/RSI values are not drawn on a dollar-price axis.

The BTC/USD badge uses shared SSE with stable tabular numbers and no per-tick
screen-reader announcement. Its observed Coinbase price stays separate from the
historical chart. Stale data remains visible with stale/reconnecting text.
Reduced motion requires no special animation override because price updates
have no animated movement.

`app/icon.svg` is the single brand source. `deploy/generate-icons.py` renders ICO
sizes and the 180px Apple PNG using librsvg. Browser icon metadata follows Next's
file convention; the in-app brand uses `/icon.svg`.

## Chart-control refinement (installed October 1 at 23:03 Eastern)

Both overview charts use green text-only Show volume / Hide volume controls.
Crypto places chart style and Reset view together below the range row. Error and
partial-history feedback occupy a reserved, fixed-height right-aligned row. Long
messages truncate visually with their full text available on hover and to assistive
technology; Retry stays visible. The chart does not move when a message appears.

Minute refresh does not replace an in-progress history window or repeatedly retry
an error. The browser retries the specific interrupted-worker Bitcoin history
failure once after two seconds, then exposes Retry if it fails again. This only
requeues display history; it cannot replay orders, research jobs or trading actions.
Already loaded bars are retained. The interruption message means a prior chart
worker left an unfinished job; it alone does not establish why that worker stopped.
Other failures remain visible for explicit retry. Hidden tabs skip minute refresh.

The repeated chart-level TradingView text is removed. A single visible attribution
link remains in the application footer, following the library's attribution guidance:
https://tradingview.github.io/lightweight-charts/docs/5.1/api/interfaces/LayoutOptions

Verification for revision `7563c751b2867a46ffc151c2d8b4adc8adaed68a`:
local type checking, production build and all 109 JavaScript tests passed. Browser
fixtures at 1440px and 390px in light/dark themes confirmed transparent volume
buttons with identical green text in both states, style/reset below ranges, no
horizontal overflow or JavaScript errors, one footer attribution link, and zero
plot movement when interrupted-history errors appear. Mobile hover summaries
stay on one line to prevent a separate wrapping-induced shift. These are isolated
browser checks, not end-to-end broker or production-provider verification.

Linux staging passed its type/lint checks, JavaScript/feed/worker/deployment suites,
production build, wheel build and manifest/preflight verification. The reviewed
stage is `/home/mjm2z/stock-watch-releases/7563c751b286`. The installer completed
at 23:03:11 Eastern and its receipt confirms the exact revision above. This was
a code-only deployment: no database migration or full database backup was needed.
All four core services are active; feed, execution and notification health passed.
The existing general-health scanner warnings remain; broker reconciliation is
matched. Recovery metadata is retained at
`/var/backups/stock-watch-releases/20261002T030251Z`. The documentation commit after staging does not alter the
reviewed application artifacts.
