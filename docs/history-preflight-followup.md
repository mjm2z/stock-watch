# Bounded handoff: history-preflight design

Status: proposed next assignment; no shared-tree implementation or production access granted. The StockWatch integration owner retains deployment/merge ownership.

Base: the closeout commit containing this file (exact SHA supplied in the final handoff), whose parent is `4b2d267850f283f01c8b9412154047588c0b840e`. Start an isolated worktree at that SHA only after ownership is handed back. Do not base work on the installed runtime or on older Bitcoin checkpoint commits.

Permitted change: only `docs/history-preflight-design.md`. Read current research/evaluation/discovery/workspace code and tests; do not modify them. Produce a code-backed design and fixture inventory for a later implementation release.

Required output:

- Separate standard visual-system backtests, strict forward-observed Bitcoin evaluation, and experimental historical discovery. Derive each protocol's warmup, chronological windows, folds and holdout needs from actual code. The standard first-fold-plus-holdout requirement must be checked rather than copied from a historical count.
- Describe requested versus available history, calendar-month/UTC boundaries, missing bars, warmup sufficiency and infeasible monthly requests. Keep data availability distinct from qualification and authorization.
- Specify reusable read-only preflight inputs/outputs and the smallest API/UI integration. Explain how to avoid network collection, evidence renewal, new orders or migration/initialization as a side effect of inspection.
- Inventory deterministic acceptance fixtures: one bar short/exact minimum, leap-year/calendar month endpoints, partial final bars, unavailable data, gaps, overlap disclosure and touched holdout. Existing engine hashes and strict/experimental policy boundaries must remain unchanged.
- Identify the separate trial/holdout-registry dependency rather than inventing a registry inside preflight. No DSR/PBO implementation, broad optimizer, new data source or policy change.

Acceptance: every formula references its current implementation; fixture expectations are explicit; remaining decisions/dependencies are listed for the integration owner. No expensive fresh research, test-count recreation, trading-capable CLI, production changes, or edits to coordinator.py, cli.py, BitcoinWorkspace.tsx or the installer. The design is reviewed before a separately scoped implementation is authorized.
