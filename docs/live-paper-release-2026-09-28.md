# Live pricing and manual paper release — September 28, 2026

## Release state

This is a partial rollout, not an operational trading launch. Both repositories'
implementation commits are pushed. No test trade, account reset, or new strategy
activation was performed.

| Component | Revision | Verified state |
| --- | --- | --- |
| StockWatch production on a1347-m | `51b45a63caba90ff42ed173b6c3b25de4de27078` | Existing installed receipt; web and Bitcoin automation timer active |
| StockWatch new release | `a8a53189f0c136c484a9e1615bb7644ae700df43` | Linux staging verification in progress; not installed |
| Autobot on a1347-m | `488d55fc989fbd28960f4b63e1f0d13c9a0de4e3` | Deployed with required Git script; installed HEAD verified; user `note-bot.service` restarted and active |
| Independent watchdog on a1347-j | Existing deployment | `home-ops-watchdog-migration.service` active; new component monitors not registered |

Autobot's StockWatch service token and allowed Telegram user configuration are
absent. New manual accounts have not been provisioned or setup-confirmed. Neither
Telegram paper execution nor new live-price production delivery is operational.

## Implemented source

See [the operations guide](live-paper-operations.md) for full behavior, constraints,
configuration, command examples, and recovery. Source includes the Coinbase
ticker/heartbeat collector and immediate SSE card; a single Bitcoin execution
owner; separate durable manual-paper accounts, drafts, confirmations, reservations,
conditional instructions, protective plans, broker reconciliation and notifications;
the browser manual workspace and scoped Autobot API; structured Telegram commands;
asynchronous cached preflight; and versioned stock corporate-action corrections.

Stock activation now checks required evidence at the broker activation boundary as
well as the UI/Telegram preview. Current corporate-action and historical-membership
evidence does not qualify stocks for activation. An unauthenticated source probe
returned HTTP 401; it does not establish authenticated coverage or entitlement.

## Verification evidence

- Local StockWatch: 389 worker tests, 88 Jest tests across 23 suites, six feed tests,
  type-check, production build, and lint passed. Lint retains three existing warnings.
  All 32 deployment-tool tests and five backup tests also passed.
- Local Autobot: 186 tests and full Ruff check passed. After deployment, 59 targeted
  tests passed on Linux. The bot restart and deployed revision were checked.
- Desktop 1280px and mobile 390px Chromium checks covered card placement, stable
  height, no horizontal overflow, reduced motion, and no JavaScript exceptions.
  The unconfigured manual workspace was visible. Historical controls remained;
  local historical data was unavailable because the production DB was not copied.
- Read-only Coinbase checks: 27 fresh events in 12 seconds locally, 37 in 12 seconds
  on Linux, one connection generation in each sample. First/last sampled source ages
  were 90/3 ms locally and 46/10 ms on Linux. These are observations, not fill or
  latency guarantees.
- Existing production LAN health returned HTTP 200 (about 1.08 seconds under host
  load). Sub-500-ms cached preflight was verified against a local fixture, not the
  production database.
- Regression coverage includes stale/gap/reconnect behavior, bounded clients,
  uncertain submission cancellation, account isolation, confirmation binding,
  partial-fill protection, execution locking, stock actions and activation gating.
  End-to-end broker paper trades and production cutover/restart verification remain
  outstanding.

The first Linux staging run was stopped during disk-bound Jest fixture writes.
The rerun uses a private `/dev/shm` fixture directory and identical lockfile-matched
dependencies from the incomplete stage. Production backup free-space requirements
are unchanged; only tiny test backups waive the production reserve.

## Remaining implementation and operational limits

- Existing stock scan/entry/exit timers have not been consolidated into a single
  account-wide execution daemon. That portion of the requested plan remains work.
- The new Bitcoin owner replaces an enabled shared coordinator timer. Legacy
  Bitcoin trading authority must be migrated through the existing account/ledger
  procedure; the installer refuses competing enabled owners.
- P&L uses broker unrealized values and reconciled equity against the confirmed
  baseline. Unknown cash flows/actions or unreconciled fills withhold total P&L;
  there is no complete tax-lot realized-P&L or external-cash-flow workflow.
- Corporate-action source coverage and historical membership still need evidence;
  stock qualification stays blocked. No paid data was purchased.
- New health routes exist in source. HomeOps registration and independent reporting
  of all three components are not yet verified.

## Operator installation and setup

Installation requires root on a1347-m. `sudo -n true` returned "a password is required".
The reviewed installer also prohibits installation during regular weekday US market
hours. Neither restriction was bypassed, and no production migration was started.

Once Linux staging is verified, run outside regular market hours on a1347-m:

```sh
sudo systemd-run --unit=stock-watch-release-a8a53189f0c1 --collect \
  /usr/bin/python3 /home/mjm2z/stock-watch-releases/a8a53189f0c1/deploy/install-reviewed-release.py \
  /home/mjm2z/stock-watch-releases/a8a53189f0c1
journalctl -fu stock-watch-release-a8a53189f0c1.service
```

The installer verifies its manifest, drains owners, backs up before additive
migration, preserves existing authority, and records the installed receipt. Inspect
the receipt and service status after completion; a staged manifest is not an install
receipt. Verify LAN Live Price/SSE, collector restart, exactly one Bitcoin execution
owner, and existing automation before calling the rollout successful.

Provision the four new manual-account credential values and distinct browser/Autobot
tokens in protected configuration as described in the operations guide. Configure
both allowed Telegram identifiers. Verify all four Alpaca account identities differ,
then preview and individually confirm the proposed $1,000/$100 manual setup. Never
reset or substitute existing accounts. Any paper test order needs its own explicit
confirmed draft.

After all health endpoints are healthy, run `deploy/register-live-monitoring.py` as
the HomeOps user on a1347-m, restart HomeOps through its established workflow, and
verify a1347-j reports feed, execution, and notification health independently.
Protective instructions require StockWatch online; broker-held orders can remain
active during outages. Follow the operations guide for reconciliation and rollback.
