# Live pricing and manual paper release — September 28, 2026

## Release state

This remains a partial rollout. StockWatch source is committed and pushed but is
**not installed** on a1347-m. The old staged release is superseded and must not
be installed. Autobot is deployed, but manual trading has no dedicated credentials
or confirmed setup. No test order, account reset, or strategy activation occurred.

| Component | Revision | State |
| --- | --- | --- |
| StockWatch production on a1347-m | `51b45a63caba90ff42ed173b6c3b25de4de27078` | Existing installed receipt; web and Bitcoin automation timer active |
| StockWatch combined-account stage | `6e7120fe1e9d26271032ffc55902722dcb345cdf` | Pushed; Linux tests, build, wheel, 32,263-file manifest and read-only installer check passed; not installed |
| Autobot on a1347-m | `a1c6ec9d0b4ff05e45021c09fc34b1eab5eb0957` | Git-script deployed; `note-bot.service` restarted and active |
| Independent watchdog on a1347-j | Existing deployment | Active; new component monitors not registered |

The previously reported StockWatch `279284f03b4c` stage was built for two manual
paper accounts and has been superseded. The incomplete `d41769dd6ed2` stage is
only a source for lockfile-matched dependencies; it is not installable. Neither
stage should be passed to the installer.

## Implementation and verification

The [operations guide](live-paper-operations.md) describes the Coinbase ticker
collector, immediate Bitcoin Live Price, separate observed and executable prices,
execution owner, manual previews and confirmations, virtual budgets, trigger and
protective instructions, durable notifications, stock-data corrections, and
rollback. StockWatch now uses **one** new Alpaca paper account for manual stocks
and Bitcoin, with separate durable $1,000 allocations and a $100 entry cap. Its
setup requires $1,000,000 actual simulated cash and an empty account. The user
confirmed the Alpaca new-account form offers that starting balance and subsequently
confirmed creating the account. StockWatch has not yet verified its balance,
positions, orders, or distinct identity through the broker API.

Local checks for the combined-account revision passed: 394 worker tests and
TypeScript type checking. Autobot passed all 188 tests and Ruff. Linux checks
passed 23 Jest suites/88 tests, six feed tests, the production build, 394 worker
tests, and wheel construction. Linux lint passed with three pre-existing warnings.
The 32,263-file manifest and `install-reviewed-release.py --check` passed on
a1347-m. The preflight explicitly reported that no files or services changed.

The prior release verification also covered desktop and mobile Live Price layout,
reduced motion, historical chart controls, Coinbase read-only feed samples,
backup behavior, execution locking, and activation gating. Those observations
were for the previous two-account stage, so they do not establish that this new
revision is installed or operational.

## Known limits

- Existing stock scan, entry, and exit timers are not yet consolidated into one
  account-wide execution daemon. Stock qualification remains blocked pending
  corporate-action and historical-membership evidence.
- The Bitcoin owner switch requires the reviewed installer to drain the previous
  coordinator and reconcile orders. A staged build alone does not do this.
- Manual P&L is withheld when broker cash, positions, fills, or fees do not
  reconcile. There is no complete tax-lot realized-P&L workflow.
- HomeOps registration and a1347-j independent checks for the three new health
  components remain unverified.
- App-managed triggers and protective instructions require StockWatch online;
  paper fills and latency are not guaranteed.

## Installation and account setup

The reviewed installer rejects weekday 09:30–16:00 America/New_York invocation
before modifying production. It also requires root on a1347-m; the available SSH
session cannot use passwordless sudo. Neither guard was bypassed. The source is
ready for review, but no StockWatch migration or service cutover has occurred.

The verified stage is `/home/mjm2z/stock-watch-releases/6e7120fe1e9d`. An
operator with sudo access can install it **after 16:00 ET** using:

```sh
sudo systemd-run --unit=stock-watch-release-6e7120fe1e9d --collect \
  /usr/bin/python3 /home/mjm2z/stock-watch-releases/6e7120fe1e9d/deploy/install-reviewed-release.py \
  /home/mjm2z/stock-watch-releases/6e7120fe1e9d
journalctl -fu stock-watch-release-6e7120fe1e9d.service
```

The installer performs a backup before additive migrations. Verify the installed
receipt, LAN Live Price/SSE, collector restart,
exactly one Bitcoin execution owner, and existing automation. Register the three
new HomeOps health checks and verify the a1347-j watchdog independently.

The operator has created the new paper account under the existing Alpaca login
with the requested $1,000,000 simulated cash. Keep it empty while setup is pending.
StockWatch must verify its actual account ID differs from both automated accounts,
its balance matches, and it has no positions or open orders. Generate a new paper key/secret for
that account; keep them in protected StockWatch configuration, never in Autobot
or chat. Set a separate scoped Autobot token and both allowed Telegram user and
chat IDs. Preview `/stockwatch setup combined`; confirm only after it shows the
expected broker balance, two $1,000 allocations, and $100 entry cap. Setup never
resets an account. Paper test orders require their own explicit confirmed drafts.
