# SEC company information

Status: release `67e2ba9211a092664c568f99c69f5cca9c8b45b3` is committed, pushed
and verified in Linux staging at `/home/mjm2z/stock-watch-releases/67e2ba9211a0`.
Production deployment and live provider verification remain pending. This is the first, context-focused phase of the free-tools roadmap.
FRED/ALFRED, LEAN and QuantConnect integrations are not included.

## What appears in Overview

The Company information panel follows the stock chart and shares its selected
symbols. Adding a stock selects that company; buttons switch the information view
without changing chart comparisons. Removing the active ticker selects the last
remaining ticker. No tickers shows a prompt to add one.

Recent filings show up to 20 supported annual, quarterly, current, proxy and fund
reports from the SEC submissions response, with amendments retained as separate
accessions. Each links to the SEC filing index, where the original report and
exhibits can be inspected. Filing date, report period and acceptance timestamp
(where supplied) are distinct. The earnings filter identifies 8-K Item 2.02;
it is not a forward earnings calendar, consensus estimate or transcript service.
This panel does not change the scanner's earnings-calendar eligibility rules.

Reported financials include revenue, net income, diluted EPS, operating cash flow,
and cash/equivalents where standard US-GAAP facts are available in the expected
units. Duration metrics use reported annual 10-K/10-K-A periods of 330–400 days;
quarterly/YTD values are not silently annualized. Cash is a point-in-time balance
from a 10-K or 10-Q. Later filed values for the same period take precedence, and
each value retains its concept, accession, filing date and period. Future filings,
invalid/nonfinite numbers and incompatible units are excluded. Periods may differ;
no growth ratios, inferred quarters or trading recommendations are calculated.
Foreign/custom-tag facts can be unavailable even when filings exist.

Fund classification uses SEC fund mappings, investment-company SIC codes and fund
filing forms. SPY's CIK 884394 is explicitly recognized as a fund trust, including
when its submissions omit SIC/series metadata. The fallback SPY identity is sourced
from the [SEC filing index](https://www.sec.gov/Archives/edgar/data/884394/0001193125-17-146441-index.htm).
Funds do not receive corporate earnings/revenue cards. The view is issuer-level:
shared fund registrants may include other series/classes; it is not a holdings feed.
Unmapped tickers show unavailable rather than using a guessed issuer.

## Collection, API and storage

`GET /api/stock/[ticker]/company` validates the symbol, reads a small indexed
projection and coalesces eligible refresh requests. It returns status, freshness,
last-check time, retry eligibility, error and the prior projection if available.
It never fetches SEC data or parses full CompanyFacts during the web request.
Database lock waits are capped at 100 ms; unavailable responses remain separate
from missing financial metrics.

`stock-watch-company-context.timer` invokes a separate oneshot worker after boot
and ten seconds after the last run finishes. One exclusive process lock owns its
queue; interrupted display jobs retain their previous data and enter a 15-minute
cooldown on restart rather than looping through repeated failures. Each invocation handles
one symbol. The worker uses the existing SEC client with the protected
`SEC_USER_AGENT` identity and at most one request per second. It has a 240-second
service timeout and a 256 MiB memory limit. It never calls a broker or submits trades.

A successful projection is eligible for refresh after six hours, on the next
request. Failed requests cool down for 15 minutes; Check again observes that
cooldown, not a force-refresh bypass. The browser polls pending work every three
seconds for at most three minutes, then offers Check again. Changing symbols
aborts the old subscription, and late responses cannot replace the selected issuer.
Existing information stays visible while queued or after a refresh failure.
These are recent reports, not a real-time filings alert service.

Migration 025 adds only the company-context projection/queue and SEC directory
cache tables. At most 20 symbols may be queued/running, at most 500 projections
are retained, and each projection is limited to 128 KiB. Old inactive projections
are evicted to make room. The two directory maps refresh daily and are bounded
to 100,000 entries each. Up to 2,000 recent submission entries are inspected;
older submissions archives are not downloaded.

The collector reuses the existing latest CompanyFacts observation when it is less
than 24 hours old. Otherwise it fetches facts transiently and stores only the small
display projection. It does not append another full SEC document, create instruments,
rewrite historical research evidence, or change signals, qualifications or orders.
Display projections are disposable and must not be treated as point-in-time research
inputs. Source and receipt dates remain visible independently of reporting periods.

## Operations and rollout

The reviewed release installer backs up before additive migration 025, drains
writers, installs the worker/timer and restores existing services. Use its normal
outside-trading-hours cutover. Older application code ignores the additive tables;
if rolling back, also stop the new company-context timer before switching runtimes.
Retain the installer recovery snapshot and matching prior runtime. No credential
changes are needed if the existing SEC refresh is already configured.

Inspect with `systemctl status stock-watch-company-context.timer` and
`journalctl -u stock-watch-company-context.service`. A stopped oneshot service
between runs is normal. API status and the visible collection timeout distinguish
pending work from available data; missing SEC identity is reported as unconfigured.
Do not interpret a successful build or fixture test as live provider verification.

Tests cover annual/YTD separation, amendments, invalid values, fund classification,
source URLs, cache reuse, interrupted jobs, failure preservation/cooldowns, request
coalescing/caps, selection races, empty selections and fund UI behavior. Release
verification also checks desktop/mobile layout, both themes, and existing suites.

## Follow-on integrations

SEC context comes first. FRED/ALFRED remain under investigation because their
current published terms raise caching/archiving and AI-use questions. LEAN should
be evaluated as an isolated research runner, using free permitted data; it must not
become a second execution owner. QuantConnect's free browser workspace can support
external comparisons, but its paid API/CLI integrations are outside the free-only
constraint. No paid subscriptions or datasets are required by this SEC feature.

## Release verification (October 2, 2026)

Local type checks and production build passed. Linux staging passed type checking,
lint (existing warnings only), all 114 JavaScript tests, eight feed tests, 416 worker
tests and 51 deployment-helper tests (one Linux platform-specific skip), followed
by worker-wheel and reviewed-manifest/preflight verification. Browser fixtures at
1440px and 390px in light/dark themes passed company/fund switching, corporate
metric suppression for funds, no horizontal overflow and no JavaScript errors.

The initial worker-suite run identified two migration-list expectations that needed
025 added; both now pass along with existing ledger-preservation checks. An initial
Node test-environment annotation conflicted with the repository's browser test
setup; the tests now use the established SQLite test environment and pass.
A direct unauthenticated local SEC probe returned HTTP 403. This does not verify
or invalidate the server's configured SEC identity; live collection must be checked
after installation. No test orders, new accounts or strategy activations occurred.
The documentation update after staging does not alter the reviewed release files.
