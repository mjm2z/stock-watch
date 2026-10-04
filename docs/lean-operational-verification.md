# LEAN operational verification — October 3, 2026

This follow-up is in progress. The historical comparison remains verified; live
failure exercises below must not be inferred from local test results.

| Check | Evidence/status |
| --- | --- |
| Deployed historical report | 720 decisions, 6 fills, 726 equity observations; zero differences |
| Browser discovery | Fixed: LEAN visible in normal `/systems?asset=bitcoin` library |
| Browser report | Existing metrics, both charts, limitations and report link render |
| Mobile | Installed fix verified at 390px: no horizontal overflow and no page errors |
| Normal library fix | Installed `7f4f4ef4bcd2` at 13:12:15 Eastern; desktop/mobile walkthrough passed |
| Linux release | 123 JS, 430 worker, 58 deployment tests (one platform skip), type-check and production build pass |
| Runner boundary tests | 22 local tests pass, including recovery, interrupted starts, timeout, oversized results, storage rejection |
| Independent monitor | Installed on a1347-j; active alongside unchanged HomeOps watchdog; two healthy observations, no incident |
| Runner restart | Passed October 3 at 13:10:33 Eastern; same container and exact retained fixture result |
| Bridge restart | Passed at 13:18:48 Eastern; resumed stable job and completed with zero differences |
| Full 30-minute timeout | Passed October 3 at 13:51:17 Eastern; repeat passed at 14:32:22; both included successful follow-up fixtures |
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

Release `7f4f4ef4bcd2` installed as code-only: no migrations or database backup
were required. Prior runtime recovery is `/var/backups/stock-watch-releases/20261003T171159Z`.
All five application services were active, LEAN health passed, and HomeOps links
were updated to the normal Systems library. The deployed browser check used no
style injection; report metrics and both charts rendered with no page errors or
mobile horizontal overflow.

Bridge recovery evidence: job `16298801-5601-4622-8dda-26bf7f27edd8`,
created at 13:18:10 Eastern. The bridge restarted at 13:18:21 during remote
research; the comparison completed at 13:18:47 with zero differences and the
verification helper exited successfully at 13:18:48. A prior separate invocation
created `ef15b967-7768-466f-bc3c-45420cbdaeaf`, also completed; these are distinct
operator verification requests, not a restarted job receiving a new identity.

## October 4 continuation

Confirmed both timeout exercises succeeded. The first used job
`8b99fe73-a363-4995-a4f1-ec1d9707d188` and follow-up
`e3520c41-228d-46d2-afcd-84d9f93daf55`. The repeat used
`bed67007-d125-46dc-84f0-2c3ac6976214` and follow-up
`9b7310a4-2f7c-4456-b3c1-a6464879d39f`. Both enforced the unchanged 30-minute
limit, required container removal, and compared subsequent fixture output with
the verified reference. At 11:13 Eastern on October 4 the runner and bridge were
healthy, the research queue empty, and the independent monitor had no incidents.
Actual outage/recovery delivery remains the next check.
