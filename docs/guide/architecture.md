# Architecture and ownership

[Application guide](../../README.md) · [Release state](../next-phase-release.md)

| Boundary | Owner and implementation | Authority |
| --- | --- | --- |
| Browser | Next.js pages, components, read-only chart context | Presentation; authenticated mutations go through explicit APIs |
| Live observations | `services/market-feed.mjs`, supervised separately | Coinbase connection only; cannot trade |
| Automated Bitcoin | Existing execution owner/coordinator | Existing accounts, qualification paths and allocations |
| Automated stocks | Existing stock/legacy workers and ledgers | Existing stock evidence gates; legacy execution timers remain |
| Manual paper | `worker/.../manual/server.py`, store, execution, protection | Dedicated combined paper account, separate $1,000 sleeves |
| Research | Existing workspace worker plus `systems/inspection.py` | Research snapshots/results; no executable registration or enrollment |
| Telegram | Autobot → scoped loopback service | User/chat-bound draft/confirmation; no broker credentials |
| Monitoring | Local component checks plus a1347-j watchdog | Read-only health, independent of application host |

The application host is a1347-m; a1347-j remains retired for application execution.
One applicable execution owner and stable client-order IDs prevent duplicate
submission streams. Do not infer permission from an account's buying power or a
successful backtest. Qualification, authorization, submission and fill are
separate transitions.

Next-phase changes reuse existing stores, Python rules, replay and workspace
jobs. `research_snapshots` is intentionally separate from `system_versions`:
a preview cannot become a discovery candidate by appearing in the executable
registry. Existing strict forward-observed Bitcoin policy and experimental
historical policy are preserved; the latter gains no new thirty-day requirement.

The request path does not perform historical replay. The workspace worker uses
the existing research lock/queue; chart collection remains a separate queue.
Manual broker validation occurs outside write transactions and commits only if
a durable state revision is unchanged. Rendering and toggling a chart calls
read-only inspection APIs and does not invoke trading commands.

The UI distinguishes manual allocations, automated systems and legacy scanner
lots. The browser-local legacy sandbox is also separate; it is not an Alpaca
account or evidence of actual paper execution.
