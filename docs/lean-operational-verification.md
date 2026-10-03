# LEAN operational verification — October 3, 2026

This follow-up is in progress. The historical comparison remains verified; live
failure exercises below must not be inferred from local test results.

| Check | Evidence/status |
| --- | --- |
| Deployed historical report | 720 decisions, 6 fills, 726 equity observations; zero differences |
| Browser discovery | LEAN missing from normal Systems library; available only through `legacy=1` |
| Browser report | Existing metrics, both charts, limitations and report link render |
| Mobile | Existing chart grid overflow reproduced; proposed sizing eliminated overflow with no page errors |
| Normal library fix | Committed and Linux-staged at `7f4f4ef4bcd2`; not installed yet |
| Linux release | 123 JS, 430 worker, 58 deployment tests (one platform skip), type-check and production build pass |
| Runner boundary tests | 22 local tests pass, including recovery, interrupted starts, timeout, oversized results, storage rejection |
| Independent monitor | Installed on a1347-j; active alongside unchanged HomeOps watchdog; two healthy observations, no incident |
| Runner restart | Passed October 3 at 13:10:33 Eastern; same container and exact retained fixture result |
| Bridge restart | Helper staged; not started |
| Full 30-minute timeout | Helper staged; not started |
| Real outage/recovery delivery | Authorized; not exercised yet |
| Authenticated browser queue/cancel | Not yet verified end to end |

Run research checks sequentially with no unrelated research queued. The runner
helper refuses to begin with unfinished jobs. It requires installed runtime
`0aef431` and uses only the bundled fixture and its retained verified result.

On a1347-d, use `/home/mjm2z/stockwatch-lean-checks/verify-operations.py` with sudo
and `--scenario restart`, then `--scenario timeout`, then `--scenario outage`.
Each invocation prints its transient service name; follow `journalctl -fu UNIT`.
Ctrl-C stops viewing the journal, not the check. Timeout uses the real 30-minute
limit, followed by a fresh successful fixture. Outage arms automatic restoration
before stopping the runner for five minutes. Do not call an outage check passed
until a1347-j records sent outage and recovery receipts.

The independent monitor's durable evidence is
`/home/mjm2z/.local/state/stockwatch-lean-watchdog/state.json` on a1347-j. It preserves
uncertain delivery without retry; message IDs mean provider acceptance, not that
the recipient read the message. Its unit is `stockwatch-lean-watchdog.service`.
The HomeOps watchdog is a separate unit and retains its original target.

The bridge helper is `/home/mjm2z/stockwatch-lean-checks/verify-lean-bridge-root.py`
on a1347-m. It creates a distinct audited replay using the retained September
input, then restarts only `stock-watch-lean.service` while awaiting remote work.
It requires a complete zero-difference result after restart. It never changes
trading authority or reuses the historical verification's job identity.

Install the corrected app only through its reviewed staged installer, separately
from active failure exercises. After installation, verify `/systems?asset=bitcoin`
on desktop/mobile and refresh HomeOps's LEAN browser link using
`deploy/register-live-monitoring.py --components lean`.

Runner restart evidence: job `7ac6309f-65f7-4d19-9d6e-f7370defe8f2`, container
`ec9a7a8ce61edffbb8c8cbf247b3c4f7d3ac633deae16e2ce222163625fb3db8`.
The synthetic job was paused, the supervisor restarted at 13:10:13 Eastern, and
the same container completed at 13:10:33. The helper compared the full result to
the retained verified fixture and exited successfully.
