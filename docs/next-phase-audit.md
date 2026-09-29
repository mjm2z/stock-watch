# Next-phase implementation audit

Baseline: clean `a99cd0c` main, September 28, 2026. Authorized by the next-phase
prompt and “Implement the plan.” This file tracks source work, not deployment.
At 23:00 ET the previously launched `6e7120fe1e9d` installer remained active,
copying its database backup (729088/10027878 pages). Do not launch a competing
installer. Manual account credentials/setup remain operator prerequisites.

| Requirement | Reachable path | Baseline finding | Change/checkpoint |
|---|---|---|---|
| Manual paper ticket | ManualPaperWorkspace → /api/manual-paper → manual/store → execution | Partial: only limit ticket; whole stock shares | Shared capability contract, market notional and fractional DAY orders, guided ticket, transaction revision guards |
| Fast live BTC | BitcoinLivePrice → /api/crypto/live → market-feed.mjs | Implemented; staging feed/UI tests from prior release | Preserve separate source, timestamps, stale states and immediate delivery |
| Chart inspection | MarketChart/StockChart → history APIs | Partial: candles exist, no account overlays; stocks adjusted | Raw stock mode, focused chart/comparisons, scoped read-only layers |
| Activity | manual outbox/fills, btc_orders, system_orders | Partial: snapshots, no unified transition table | Prospective durable transitions; no fabricated historical events |
| Draft preview | ResearchWorkspace → workspace jobs → systems/research | Missing: publish required for replay | Non-executable snapshots and queued previews using same engine |
| Research learning | research_lineage/discovery_trials/scenarios | Partial: retained runs, no preregistered paired experiment | Frozen plans, attempts, reviews, exposure registry; no promotion |
| Performance | engine/replay and manual/accounting | Existing full-resolution metrics; manual broker scope combined | Keep scope/cost labels, hide unsupported allocation returns |
| Stock qualification | stock preflight → evidence gates | Raw input readiness is not qualification | Preserve corporate-action/membership gates and corrected accounting |
| Favicon | app/icon.svg vs favicon.ico/apple-icon.png | Separate assets can diverge | Derive raster variants from canonical SVG |
| Deployment | reviewed installer, independent watchdog | Installation in progress, not verified installed | Tests, artifact identity, installer ownership and operator steps recorded separately |

Read boundaries: broker credentials remain server-only. Chart visibility cannot
submit commands. Manual and automated records remain separate by account, asset,
and owner. Research snapshots never enter `system_versions`, enrollments or
funded allocations. Existing qualification policies are unchanged.
