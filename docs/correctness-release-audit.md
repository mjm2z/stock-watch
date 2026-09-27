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

- Historical SIP entitlement is not yet verified on the protected account. The read-only probe is prepared. The production scanner still uses IEX, including its existing absolute-volume thresholds; their consolidated-market interpretation remains a known limitation pending a separately versioned comparison.
- No historical membership, delisting, corporate-action, or missing-session evidence is invented. Dataset reports surface retained claims and unavailable prerequisites. This change does not implement a corporate-action replay engine.
- Fundamentals v2 is a prospective shadow report. It does not replace published annual features, reconstruct missing filing acceptance times, or backfill all historical CompanyFacts.
- Account marks start prospectively. Missing flow-event valuations invalidate the full-period result; there is no automatic restart of the measurement baseline. Broker cash/equity remains visible. Funding-matched benchmarks and sleeve-level unitization remain unavailable. The legacy matched-entry-cost SPY comparison is a separate cohort proxy.
- Continuous research replay, complete trial-return matrices, DSR/PBO, history preflight, holdout tracking, execution attribution, aggregate exposure controls, proposal experiments, and broad UI consolidation belong to later stages. They are not described as delivered by Release 1.

## Verification and rollout

Local checks: 360 Python tests plus 25 deployment tests; 79 web tests; TypeScript and production build passed. Existing lint warnings remain in app/api/analyze/route.ts, components/Navigation.tsx, and lib/claude.ts (see build output for exact locations). Browser smoke used isolated non-sensitive fixtures at 390px and 1440px on Overview, Paper trading, Operations, and Crypto: all HTTP 200, no horizontal overflow, no JavaScript exceptions. Performance/scans/capabilities APIs returned 200, invalid asset 400, and missing worker readiness 503. Screenshots were inspected locally; these are fixtures, not production results.

Production baseline checked: a1347-m still reports 8467b6f; web and authorized Bitcoin automation timer active. No production migration or strategy change has occurred during implementation. Deployment requires a reviewed Linux build/wheel, root installation, then live readiness/reconciliation verification. Migration 020 requires the full backup path; later unchanged-schema releases retain the fast code-only path.
