# Orders, allocations and accounting

[Application guide](../../README.md) · [Setup / Telegram reference](../live-paper-operations.md)

One manual Alpaca paper identity serves two virtual allocations. Setup verifies
that identity differs from both automated account IDs, the broker account is
empty and simulated cash equals $1,000,000. The operator confirms both $1,000
budgets and $100 entry cap. No account reset or fallback to automated credentials
occurs. Alpaca credentials remain in protected StockWatch configuration; Autobot
receives only its separate scoped service credential.

The capability JSON is shared by browser and worker. Market buys use `notional`
and never send both `qty` and `notional`. Stored requested quantity is zero for a
notional buy, so reconciliation validates cumulative notional instead of applying
a fictional estimated-quantity ceiling. Partial fills reduce the remaining dollar
reservation. Non-finite, negative, regressing or excessive fills require
reconciliation; unknown statuses do not release reservations silently.

**Worked manual trace (fixture arithmetic, not an order):** a $50 market buy
reserves $50.50. If $30 fills, the remaining reserve is $20.20. Cumulative broker
fill observations deduplicate by instruction/quantity. The fill establishes owned
quantity; price changes do not alter the original notional budget. An uncertain
POST stays reserved and is looked up by the same client-order ID. A duplicate
Telegram update or browser confirmation cannot submit it again.

The same account's other allocation cannot spend that reservation. Sell checks
use both broker-owned quantity and durable sleeve attribution, less reservations.
Direct external broker activity causes reconciliation blockers. Quote validation
is fresh at preview, confirmation and dispatch. Manual validation runs outside
SQLite write locks, followed by an immediate transaction and relevant-state
revision recheck.

Protective plans attach to an isolated entry and size from actual fills. Entry
cancellation and child-order reconciliation precede replacements. Stock fractional
exits use broker precision and DAY; small quantities are not rounded to whole
shares. An expired child does not cancel its protective plan. Local exits are
not broker-atomic OCO, require StockWatch online, and can remain unfilled at their
price-protected limits. Canceling a plan is an explicit confirmed instruction.

Manual spending accounting conservatively retains the 1% allowance against
cumulative filled value until actual fee treatment is available. Snapshot
“available” cash subtracts current pending reservations. Broker total P&L is
withheld unless cash, quantity and posted fees reconcile. Prospective allocation net returns use the $1,000 opening budget, attributable
posted fees and reconciled broker marks. Minute valuations and observed high-water
marks are retained; intervals before collection are not reconstructed. Unknown
fee attribution withholds allocation P&L. Complete tax-lot realized P&L is unavailable.
The $1M broker balance is not either allocation's performance denominator.

Existing stock split/reverse-split adjustments, stop basis, pending quantities,
indicator price/volume normalization, momentum ordering and dividend identity /
entitlement / payment sequencing remain in the corrected engine. New chart/raw
modes do not rewrite historical orders. Correct arithmetic does not establish
corporate-action coverage, point-in-time membership or historical sector truth;
stock qualification remains blocked where those are absent.
