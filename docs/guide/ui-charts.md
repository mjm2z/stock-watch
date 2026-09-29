# UI, chart inspection and activity

[Application guide](../../README.md)

The sidebar retains Stocks/Crypto context. Paper trading leads to the manual
allocation workspace with visible links to automated portfolios and legacy
scanner lots. Forms use labelled inputs, keyboard-operable controls, bounded
responsive tables, explicit loading/error/empty states and preview/confirmation.
Read-only users can inspect records but cannot submit mutations.

Stocks Overview focuses on SPY initially. A browser-local watchlist stores symbols
only; it contains no credentials. Choose presets, custom UTC dates, 5-minute /
hourly / daily display resolution, line or candles and volume. Up to five other
symbols appear in normalized comparison on common timestamps. Prices are not
forward-filled through absent observations. Raw and adjusted caches are separate.
The focused price chart and normalized comparison remain separate views.

Existing Lightweight Charts 5 is reused, including attribution, accessible data
tables, pan/zoom and resize cleanup. Current overlay price lines update without
rebuilding the base chart. Larger data/mode changes preserve the viewport.
Comparison series share a percentage scale; different autoscaled axes must not
make unequal returns look equal. No drag-to-trade behavior is implemented.

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

Bitcoin Live Price uses shared SSE with stable tabular numbers and no per-tick
screen-reader announcement. Its observed Coinbase price stays separate from the
historical chart. Stale data remains visible with stale/reconnecting text.
Reduced motion requires no special animation override because price updates
have no animated movement.

`app/icon.svg` is the single brand source. `deploy/generate-icons.py` renders ICO
sizes and the 180px Apple PNG using librsvg. Browser icon metadata follows Next's
file convention; the in-app brand uses `/icon.svg`.
