# Execution status and liquidity review — September 17, 2026

## Release

Staged at `/home/mjm2z/stock-watch-status-20260917` on a1347-j.
Install: `sudo bash ~/stock-watch-status-20260917/deploy/install-status-root.sh`.
This release changes only the website. It leaves worker code, database schema,
strategy parameters, order limits and scheduled trading services unchanged.
The installer verifies the Linux build/source manifest, keeps rollback files,
switches the web build, checks the new endpoints, and restores the previous
website on failure. The installer runs independently of the SSH connection.

## Execution view

- Live countdown uses the broker exchange calendar, plus the same 15-minute
  opening/closing delays as the dispatcher. Holidays and early closes come
  from the provider; New York offsets account for daylight saving time.
- Actual systemd timer states and recent worker/dispatcher completions determine
  scheduler health. Successful idle checks are not stored in operation history,
  so that history alone cannot establish whether the scheduler is alive.
- Reads the configured strategy ID, rather than assuming the newest strategy
  in the database is the one being executed.
- Checks missing credentials, broker drift, stale or failed service ticks,
  stopped timers and missing calendar. Unavailable status never shows as ready.
- A missed scan remains a visible issue even when the countdown advances to
  the next session. A strategy promoted midday is not blamed for earlier scans.
- Last successful scan and collection times are distinct from scheduled paper
  success. Fresh collection does not imply every underlying filing/bar is fresh.
- Updates every 15 seconds; an unsuccessful refresh replaces readiness with
  an explicit unverified state. Countdown runs locally each second.

## Readable history

Rejection reasons, order events and percentages have plain-English formatting.
Raw codes, identifiers and original audit payloads remain expandable under
Technical details. Existing stored records are unchanged.

## Investigation results

The September 17 1:13:09 PM Eastern validation scan contains 503 companies:
326 high risk, 149 medium, 28 low; 501 are below the score threshold; one is
also rejected for insufficient data. Rejection reasons overlap. Only MRNA is
rejected solely on risk under the existing score, while MRK qualifies across
four horizons. These are development validation records, not four distinct
companies or proof of four broker fills.

The current risk classifier flags a company high risk when ANY of these hold:
- average daily close × volume over 21 bars is below $20 million;
- annualized 21-return volatility exceeds 60%;
- drawdown over 63 closing bars is worse than −30%.

Liquidity also contributes to the ranking score. Removing its veto alone is
not a valid simulation of switching feeds: scores would also need recomputation.

Alpaca's feed documentation confirms IEX is a single-exchange feed; its volume
is not consolidated market volume:
https://docs.alpaca.markets/us/docs/market-data-faq

A read-only sample of five highest-scoring high-risk companies used the current
Alpaca IEX chart endpoint, with 253 daily bars through September 16, excluding
the unfinished September 17 bar. This is a fresh diagnostic sample, not a claim
that historical frozen scan inputs have been independently verified.

| Company | 21-bar average IEX dollars | Annualized volatility | 63-bar drawdown | High-risk trigger(s) |
| --- | ---: | ---: | ---: | --- |
| MRNA | $109.07M | 611.4% | −34.1% | volatility and drawdown |
| GEN | $12.04M | 29.3% | −7.2% | liquidity only |
| APA | $16.95M | 40.0% | −7.2% | liquidity only |
| CRM | $153.32M | 82.8% | −9.7% | volatility only |
| PAYX | $11.98M | 24.4% | −9.9% | liquidity only |

MRNA's supplied series includes a close change from $62.93 on August 18 to
$174.27 on August 19 (+176.93%), then $133.23 on August 20 (−23.55%). CRM's
August 27 close is +22.57% from August 26. These are observations in the
provider's adjusted IEX dataset, not independently established market moves.
They warrant cross-feed and corporate-action validation before treating the
computed volatility as an investment finding or calibrating new thresholds.

### Appropriate next step

Use the new Operations diagnostics to measure the full latest scan from frozen
feature inputs: liquidity-only triggers, overlapping volatility/drawdown triggers,
missing inputs and risk-only rejections. Then compare aligned completed-session
IEX and consolidated data (subject to existing entitlement), investigate outlier
bars/corporate actions, and rerun scores and outcomes on the comparison dataset.
Do not multiply IEX volume by a constant or lower thresholds merely to generate
more trades. No subscription was purchased and no strategy rules were changed.

## Validation

40 JavaScript tests pass on macOS and Linux; both production builds pass.
Tests cover early closes/DST, stopped and unavailable timers, stale and failed
scheduler ticks, overdue windows, newly promoted strategy behavior, configured
strategy selection, company de-duplication and overlapping/missing risk inputs.
Browser checks cover countdown, readiness transitions, failed-refresh recovery,
mobile width, human-readable event formatting, retained raw audit details, and
SQLite-backed liquidity API. Production verification follows the administrator
installation.

## Production verification

Installed successfully September 17, 2026, 2:13:49 PM Eastern. Live execution
endpoint reports ready, no issues, all three timers active with successful runs,
broker positions matched, next close scan 4:15 PM and maintenance 5:15 PM Eastern.
Health endpoint reports OK. The production diagnostics from frozen scan inputs show:
503 companies; 326 high risk; 285 below the $20M liquidity threshold; 269 whose
only high-risk trigger is liquidity; 30 volatility triggers; 42 drawdown triggers;
zero missing risk inputs. Triggers overlap. All 269 liquidity-only high-risk
companies also fail another qualification rule (the ranking threshold), so removing
only the liquidity veto would not make them qualify under their existing scores.
These frozen-input counts supersede inference from the five-stock fresh-bar sample.
