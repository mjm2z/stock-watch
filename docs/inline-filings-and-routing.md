# Inline SEC filings and LAN routing

## Application behavior

In Stocks Overview, select a chart ticker, then choose **View details** on a recent
filing. One filing expands at a time. **View original** remains available. Selection
changes cancel the previous browser request. The browser polls only while collection
is queued/running, at most three minutes; failures offer an explicit retry.

The application returns an indexed cached projection immediately and queues bounded
background work. The existing company-context service owns both queues under its
exclusive lock and processes the oldest request. Nothing in this path places orders,
changes qualification, or downloads documents synchronously in a web request.

The panel displays escaped primary-document text, recognized Item section excerpts,
and financial values whose CompanyFacts accession matches the selected filing exactly.
Units, period starts and ends remain explicit; comparative periods can appear together.
Amendments are distinct. No annualization, forecasts, generated summaries or latest-fact
substitutions occur. Funds retain their issuer-filings presentation without corporate
metrics. Standard US-GAAP concepts have limited coverage; custom/IFRS tags may be absent.
[SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
describes the source data and its taxonomy limitations.

For earnings-related 8-K filings, an exhibit is included only when the filing index
unambiguously identifies one EX-99 document with earnings/results wording. Otherwise
only the primary document is extracted; the original index provides exhibit access.
Source excerpts are incomplete, can include the table of contents, and lose table
layout. They are not a replacement for the original filing. Scripts, styles, hidden
inline-XBRL, embedded objects and explicitly hidden elements are excluded. PDF/OCR
and arbitrary URLs are unsupported. Document redirects are rejected rather than followed.

## Storage and recovery

Migration 026 adds `filing_details` in the existing application database, separately
from trading records. At most five requests are pending/running, with one worker.
Each downloaded document is capped at 20 MiB and discarded after extraction. Each
JSON result is capped at 512 KiB; retained payloads total at most 64 MiB. Opening
excerpts are capped at 40 KB and up to 12 recognized sections at 8 KB each per document.
Completed projections are pruned after 30 days during company-context timer activity, and
oldest completed results are evicted before exceeding the aggregate byte limit.
Interrupted jobs become unavailable with a 15-minute cooldown; existing payloads
remain available as stale evidence. Successful results are reusable for 30 days.
SEC requests use the configured contact identity and the worker's one-request/second
limiter. No new paid service or repo is needed.

## Scroll behavior

Vertical tracks are hidden without disabling scrolling. Source excerpts are named,
keyboard-focusable regions; long diagnostic text wraps instead of forcing horizontal
scrolling. Tables retain horizontal overflow. Chromium/WebKit use zero-width vertical
tracks; Firefox uses `scrollbar-width: none` on vertical-only containers. Horizontal
scroll areas retain their track. No content is removed to hide scrollbars.

## Port-free LAN address

After separate proxy activation, the canonical URL is **http://stockwatch.home.arpa/**.
DNS points to a1990 (192.168.4.36), whose existing `sandbox-http.service` nginx forwards
to a1347-m (192.168.4.35:3001). The backend and loopback collectors remain in place.
A LAN-restricted compatibility listener on a1990:3001 keeps old hostname bookmarks
working after DNS expiry. Host and forwarded scheme are preserved for same-origin
checks; SSE buffering/cache are disabled with a one-hour read timeout.

The shared configuration is `/etc/home-ops/lan-proxy.conf`; DNS configuration is
`/etc/systemd/system/sandbox-dns.service`. HomeOps, JobWatch, Sandbox and HTTPS routes
are preserved. The canonical URL depends on both hosts. Direct backend health checks
remain useful to distinguish proxy failures from application failures.

`deploy/activate-stockwatch-domain.py` runs on a1990 and prints a diff by default.
`sudo python3 activate-stockwatch-domain.py --apply` validates dnsmasq/nginx syntax,
checks compatibility-port availability, backs up both files, activates the change,
and checks StockWatch (both ports), sister routes and services. Failure restores the
previous files and restarts the original services. Unexpected existing routes abort.
The root step requires the operator's sudo password; staging alone changes no routing.

Browser preferences stored in localStorage belong to an origin: moving from :3001
to port 80 starts a separate preference store. Server-side accounts, records and
allocations are unaffected. Keep the backend URL available for diagnosis. For rollback,
restore the matching `.before-stockwatch-*` proxy and DNS backups together, then
`systemctl daemon-reload` and restart `sandbox-http sandbox-dns` on a1990.

## Verification and rollout

Local tests cover issuer/accession authorization, queue coalescing and capacity,
cooldown/stale payload preservation, safe filenames, hidden text, section extraction,
exact-accession facts, interrupted workers, route preservation and proxy idempotence.
A reviewed application stage must run the full Linux checks before migration 026.
The release installer backs up before migration. No test trades are authorized by
these UI checks. Live source coverage, advancing SSE through the proxy, auth behavior
and both installed identities must be checked after the separate root installations.

After activation, `deploy/register-live-monitoring.py --components proxy` registers
an independently checked proxy market-feed endpoint in HomeOps. Its default
still registers the three direct-backend component checks; no monitor is silently
switched to depend solely on the proxy. Follow the helper's restart instructions.

### October 2 verification

Application source revision: `2d69d5241ee3beac061be72d4073d5f553ab6fee`.
Local checks passed: 116 Jest tests (32 suites), 422 Python worker tests,
53 deployment tests, eight feed tests, TypeScript checking, lint (existing warnings)
and the production build. Chromium checks at 1440px and 390px in light/dark themes
verified expansion, keyboard scrolling, no horizontal page overflow and no page
errors. Firefox was not installed locally, so its scrollbar treatment still needs
an actual Firefox smoke test. Fixtures establish rendering, not live SEC availability.

The proxy helper was staged at `/home/mjm2z/activate-stockwatch-domain.py` on a1990;
its dry run alters only the StockWatch virtual host and DNS address. Existing
HomeOps, JobWatch, Sandbox and StockWatch upstream routes returned HTTP 200 before
activation. No proxy or DNS configuration has been activated by staging.

Linux staging completed successfully at
`/home/mjm2z/stock-watch-releases/2d69d5241ee3`. The full frontend/feed/worker/deployment
checks, build, wheel packaging, manifest verification and installer preflight passed
(one platform-specific deployment test skipped). Root application installation and
proxy activation remain pending; the installed receipt still identifies `67e2ba9`.

Install from an operator terminal:

```sh
ssh -t a1347-m 'sudo systemd-run --no-block --unit=stock-watch-release-2d69d5241ee3 --property=Type=oneshot --property=TimeoutStartSec=8h /usr/bin/python3 /home/mjm2z/stock-watch-releases/2d69d5241ee3/deploy/install-reviewed-release.py /home/mjm2z/stock-watch-releases/2d69d5241ee3'
```

Monitor locally with `python3 deploy/monitor-release.py --unit stock-watch-release-2d69d5241ee3.service --watch`.
After installation completes and its receipt/health are verified, activate routing:

```sh
ssh -t a1990 'sudo python3 /home/mjm2z/activate-stockwatch-domain.py --apply'
```


### Production verification — October 2, 23:15 Eastern

Both application and proxy activation are complete. The installed receipt identifies
`2d69d5241ee3beac061be72d4073d5f553ab6fee`, installed at 23:12:45 Eastern with migration
026 and a fresh verified backup at `/var/backups/stock-watch-releases/20261003T025852Z`.
The installer journal records successful completion; the later missing transient-unit
file message is cleanup noise, not an installation failure.

`stock-watch-web`, market-data, execution and manual-paper services are active, as
is the company-context timer. Feed, execution and notification health pass through
the port-free proxy. DNS answers 192.168.4.36. A five-second SSE sample through port
80 contained advancing event IDs 296–301 in the current connection generation;
the sample was intentionally stopped by curl's time limit.

AAPL filing `0000320193-26-000020` completed live background extraction: 39,497
characters of primary-document excerpt and 16 exact-accession financial facts,
with no collection error. This verifies one filing, not universal issuer/exhibit
coverage. Firefox smoke testing and registration of the optional separate HomeOps
proxy monitor remain follow-up items. No test orders were submitted.


### Follow-up verification — October 2, 23:38 Eastern

Firefox 155 passed live checks at 1440px and 390px: vertical scrollbar width `none`,
keyboard PageDown advanced source excerpts by 288px, and neither viewport had
horizontal page overflow. AAPL earnings filing `0000320193-26-000018` returned
3,446 characters of primary text with no error; no unambiguous earnings exhibit
was extracted. SPY was correctly classified as a fund. Its NPORT-P document
`0001410368-26-089410` is unsupported by the HTML/text extractor and returned an
explicit unavailable-format message; fund document extraction remains limited.

The HomeOps server on a1347-m cannot resolve the LAN hostname through its default
resolver. The registration helper therefore checks the dedicated compatibility
proxy listener at `http://192.168.4.36:3001/api/health/market-feed`, retaining the
canonical browser URL separately. This verifies proxy HTTP reachability, not LAN
DNS or port-80 routing. HomeOps reported the check reachable (HTTP 200, 56ms) at
03:37:29 UTC. The existing three direct component checks were preserved and their
browser links, plus the parent StockWatch link, now omit the port. Configuration
backups were retained; both HomeOps user services restarted and are active. The
helper is installed separately at `/home/mjm2z/register-stockwatch-monitoring.py`;
application revision remains `2d69d52`. Four registration regression tests pass.
The a1347-j collector/connectivity cron schedules remain present; separate watchdog
alert delivery was not tested or triggered.

General StockWatch health remains degraded by old operation rows still labelled
running, including work-once from October 1 and backup/dispatch/exit operations
from September 29–30. The latest broker reconciliation is matched and no recent
operation failure is reported. Repairing interruption recovery requires checking
actual ownership and preserving the audit trail; this verification did not rewrite
those rows or submit paper orders.
