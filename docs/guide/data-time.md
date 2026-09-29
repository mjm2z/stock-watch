# Data sources, timing and freshness

[Application guide](../../README.md) · [Existing feed operations](../live-paper-operations.md)

Coinbase Advanced Trade public `ticker` and `heartbeats` provide BTC-USD
observations. The collector validates sequence continuity, positive finite
prices, source age and heartbeat age. It reconnects with bounded backoff/jitter
and requires fresh subscription evidence. The snapshot includes generation,
event ID, source timestamp, local receipt timestamp, freshness and connection
state. SSE clients receive a snapshot and changed prices; bounded queues protect
against slow consumers. The shared browser subscription retains the last valid
price during reconnect and rejects older observations in the same generation.

The display has no price polling interval. Browser painting is naturally frame
limited; a 250 ms local timer only marks stale evidence. Heartbeats older than
three seconds or observations older than five seconds are not new trigger
evidence. The collector's source and receipt checks remain authoritative.

Alpaca US historical candles are not Coinbase ticks. Alpaca execution quotes,
orders, balances, fills and fees remain authoritative for execution. Coinbase
can wake exit evaluation, but Alpaca validates price-dependent exits and account
risk. Periodic Alpaca reconciliation and already-authorized exits continue when
Coinbase is unavailable. Source-event age, receipt-to-dispatch, trigger-to-dispatch
and broker acknowledgement are different measurements; do not report one as
end-to-end execution latency.

Stock charts use labelled Alpaca IEX history when configured. Raw mode preserves
broker-price units. Adjusted analytical mode disables raw overlays; Yahoo fallback
has provider-defined treatment and also disables them. Custom UTC dates and
5-minute/hourly/daily display resolutions do not change stock daily decision
semantics. Stock custom conditions use batched IEX quotes during regular sessions.
IEX is not a claim of a consolidated whole-market quote feed.

System decisions use completed bars and known input availability. Preview rule
inspection receives the replay engine's actual history after split handling and
BTC gap resets. It does not compute a second set of browser indicators. Weekly
and monthly datasets must match their declared timeframe; missing history is not
fabricated. For stocks, a next decision boundary requires retained exchange
calendar evidence; for BTC it is the next expected timeframe boundary, still
conditional on fresh data arriving.

**Worked BTC trace:** a fresh Coinbase tick appears immediately in Live Price.
A local `above` instruction sees the current condition, then obtains an Alpaca
quote and checks its saved limit, expiry, cash and ownership. Intent is already
durable. Dispatch and acknowledgement are audited separately. A Coinbase touch
is not a fill, and recovery evaluates the current condition rather than replaying
missed ticks.

**Worked stock trace:** SPY daily raw bars support chart inspection. A draft rule
on those bars is simulated and remains research-only. The stock-data preflight
may show basic inputs available while corporate-action or membership evidence is
unverified. That state permits labelled exploration but cannot authorize stock
systems. The corrected split/dividend engine does not certify source coverage.
