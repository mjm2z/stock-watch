# Read-only economic context

## Setup status

Source implementation passed release validation. The separate
private [stockwatch-macro](https://github.com/mjm2z/stockwatch-macro) repository has
been created. Service `f0469ac74e53d8757692b1ab66163028db7b90f4` and application
`4875c7a4f2f4` are staged and verified. Neither is installed yet. The operator
has not created a FRED API key; no live provider observations have been verified.
The remaining LEAN authenticated-browser validation is explicitly deferred until
these integration setups are complete.

## Application behavior

Economic context is a shared sidebar workspace for stocks and crypto at `/macro`.
It displays inflation (CPI year-over-year), unemployment, the effective federal
funds rate, and the real GDP level. GDP uses its published units rather than being
labelled a growth rate. Each card shows observation period, provider update date,
original publisher, seasonal adjustment, FRED source link and recent observations.
Missing readings are unavailable, never zero. CPI requires the same calendar month
one year earlier; a missing month never shifts the denominator.

These are revised current observations. They never become strategy inputs,
triggers, AI summary inputs or purported point-in-time backtest evidence. ALFRED
historical-vintage/backtest integration is deferred. Existing SEC and LEAN services
remain independent. No paid QuantConnect subscription or hosted integration is
part of this setup.

## Services, storage and interfaces

`stockwatch-macro.service` runs on a1347-m using a separate DynamicUser and binds
only `127.0.0.1:9034`. `/v1/context` returns data plus configuration/freshness state;
`/health` returns HTTP 503 until configured, collected and healthy. StockWatch
proxies these via read-only `/api/macro` and `/api/health/macro`, with a three-second
timeout and 2 MiB response cap. The public endpoints contain no credentials and
accept no provider queries or mutations.

The collector requests a fixed four-series allowlist and source metadata every six
hours; failures retry after fifteen minutes. It fetches five years to derive
calendar-year CPI changes, retaining only 36 recent observations per series and
bounded source metadata. A complete successful refresh atomically replaces
`/var/lib/stockwatch-macro/context.json`. No ticks, research arrays or duplicate
versions are stored, and the main StockWatch database is untouched. Each upstream
response is capped at 2 MiB; source notes are preserved whole within a 64 KiB field
limit rather than truncating ownership information.

Failures keep prior dated observations visible and mark updates unavailable.
Snapshot age above 24 hours is stale; observation dates and collection timestamps
are separate. A monthly observation is not falsely described as old simply because
it is not dated today. The service has 128 MiB memory and 20% CPU limits.

## Operator setup and verification

Create a personal key at https://fred.stlouisfed.org/docs/api/api_key.html.
Do not paste it in chat. After installing the reviewed service, use
`sudoedit /etc/stockwatch-macro/provider.env` on a1347-m, setting `FRED_API_KEY`.
The root-owned environment file stays private; the web process never reads it.
Restart only `stockwatch-macro.service` after saving. The installer preserves
existing configuration and may be installed unconfigured without pretending live
data works. It creates no provider account and makes no purchase.

Verify all four series, units, source dates and source links against the provider
once configured. Register HomeOps macro health only after `/api/health/macro`
reports healthy. Validate desktop/mobile and both asset navigation states. Retain
failure/null/stale tests. Revisit the deferred LEAN browser preview/queue/cancel
check after the other setups finish. Never use successful fixture tests as proof
of live provider access.

## Provider terms

Current FRED services/API terms were reviewed October 4, 2026:
https://fred.stlouisfed.org/legal/
https://fred.stlouisfed.org/docs/api/terms_of_use.html
The current pages describe personal-use subset apps; the old 2024 announcement
quoted in previous notes should not substitute for current terms. AI-related
restrictions and per-series ownership remain relevant. The UI displays the API
endorsement disclaimer, source attribution and terms link. Reassess usage before
adding AI features, redistribution or historical research retention.

## Pre-install verification — October 4

Nine macro-service tests passed locally and on Linux, including a real loopback
HTTP check for unconfigured status; the systemd unit passed validation. StockWatch
Linux staging passed 125 JavaScript tests, 430 worker tests and 58 deployment tests
(one platform skip), type checking, lint with existing warnings and production build.
Synthetic-data browser checks passed at 1440px and 390px with no page errors or
horizontal overflow. These checks do not establish FRED access or real values.

Staged service: `/home/mjm2z/stockwatch-macro-releases/f0469ac`.
Staged application: `/home/mjm2z/stock-watch-releases/4875c7a4f2f4`.
Service installation awaits the operator's sudo command. After installation,
credential configuration, live provider checks and dashboard deployment remain.
