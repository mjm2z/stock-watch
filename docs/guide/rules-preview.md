# Rules and draft previews

[Application guide](../../README.md)

A visual document specifies asset, decision timeframe, allocation, holding
period, stop-loss/take-profit settings and entry/exit groups. Supported operands
are close/open/high/low, volume, SMA, EMA, RSI, average volume, prior high/low and
finite constants. Groups use ALL/ANY, with existing depth/condition limits.
Crossovers compare the current and previous eligible values; missing inputs are
unavailable, not false. Recursive indicators retain the existing bounded-history
semantics.

Draft save uses an integer revision and conditional update. A second browser
with an older revision receives a conflict instead of overwriting the saved
configuration. Publishing requires the saved revision and freezes its payload;
later edits cannot modify the queued publication. Published versions remain
immutable.

Inspection creates a `research_snapshots` row and `preview` workspace job. It
never calls `register_version`, discovery, enrollment, qualification or broker
adapters. The worker loads retained dataset bytes, verifies their hash and
asset/timeframe, then uses the existing replay and rule evaluator. A passive
inspection callback receives the same histories as replay, including corporate
actions and gap resets. The callback does not change decisions or cash flows.

The inspector shows the latest completed retained bar, operand values,
true/false/unavailable conditions, available history, simulated decision and next
expected boundary. This is a retained-data inspection, **not a live signal panel**.
Historical preview reports a continuous $1,000 simulation over the selected
scoring interval, with earlier retained bars available for warmup. Existing
fold analysis is separate and retains its original capital convention.

The result freezes snapshot/configuration, dataset, engine hash, costs, sizing,
interval and limitations. Editing inputs marks the result outdated; a response
for an older editor state cannot become its current preview. A failed/cancelled
job cannot grant authority. Cache reuse verifies the same identity and retains
the original age; every access is still recorded as exploratory interval exposure.

Input readiness, warmup, scored coverage, feasible folds, source treatment and
execution authority are distinct. There is no single probability-like score.
Publication remains a separate step, followed by existing observation and
paper-policy checks. Stock evidence gates and both Bitcoin qualification paths
are preserved. The old [preflight follow-up](../history-preflight-followup.md)
is a historical scope record, not a restriction on this authorized next phase.
