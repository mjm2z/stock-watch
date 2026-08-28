# a1347-j deployment

These units run the dashboard, check the exchange calendar every five minutes,
process durable jobs once per minute, check the approved S&P universe source
before each trading day, reconcile paper lots, broker account
positions/non-trade activities, outcomes, and portfolio/SPY snapshots twice per
trading weekday, refresh SEC data daily, and retain 14 verified daily SQLite
backups. All broker calls remain restricted to Alpaca's paper endpoint by
application code.

## Prerequisites

- Debian/Ubuntu host with systemd, Python 3.12+, and Node 22.13+
- Repository installed at `/opt/stock-watch`
- Dedicated `stock-watch` system user and group
- A trusted local network from which clients can reach TCP port 3001

The dashboard listens on TCP port 3001 on the host's network interfaces. Do not
forward that port from the router or expose it to the public internet: v1 has
no user authentication. Restrict access to the trusted LAN with the host and
network firewalls.

The web unit grants its `stock-watch` process write access to the private state
directory because SQLite WAL readers may need adjacent shared-memory state.
The dashboard itself still opens the database read-only and immediately enables
SQLite `query_only`; the filesystem exception does not authorize SQL writes.

## Install

Stage the secret-free working tree as `/home/mjm2z/stock-watch-staging`, review
`deploy/bootstrap-a1347-j.sh`, then run this single privileged bootstrap on the
host:

```bash
sudo bash /home/mjm2z/stock-watch-staging/deploy/bootstrap-a1347-j.sh
```

The script pins the official Node 24.16.0 LTS Linux archive by SHA-256, installs
the Ubuntu `python3.12-venv` package when missing, installs the application
under `/opt/stock-watch`, creates the dedicated system account and state
directories, initializes SQLite, builds the dashboard, and starts only the web
service. It deliberately leaves every data, worker, maintenance, and backup
timer disabled until credentials and an approved universe have been configured.

For later releases after automation is enabled, use the update wrapper instead
of invoking bootstrap directly:

```bash
sudo bash /home/mjm2z/stock-watch-staging/deploy/update-a1347-j.sh
```

It records the enabled timers, stops timers and services, runs the same verified
bootstrap and migrations, and restores only the timers that were enabled before
the update. This prevents a timer from starting a half-installed worker.

Equivalent manual installation commands are retained below for audit and
recovery. Run them as an administrator after copying the repository:

```bash
useradd --system --home /var/lib/stock-watch --shell /usr/sbin/nologin stock-watch
install -d -o stock-watch -g stock-watch -m 0700 \
  /var/lib/stock-watch /var/lib/stock-watch/data /var/backups/stock-watch
install -d -o root -g root -m 0700 /etc/stock-watch
install -o root -g root -m 0600 deploy/stock-watch.env.example \
  /etc/stock-watch/stock-watch.env
python3.12 -m venv .venv
.venv/bin/pip install ./worker
npm ci
npm run build
.venv/bin/stock-watch-worker init-db \
  --database /var/lib/stock-watch/stock-watch.db
chown -R stock-watch:stock-watch /var/lib/stock-watch /var/backups/stock-watch .next/cache
install -o root -g root -m 0644 deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now stock-watch-web.service
```

Edit `/etc/stock-watch/stock-watch.env` before enabling any unit and use only
paper-account credentials. Import an approved S&P 500 universe snapshot before
the first dispatch. The checked-in strategy remains in `development`, so scans
cannot create order intents until a separately reviewed strategy version is
explicitly promoted to `paper`.

`STOCK_WATCH_STRATEGY_ID` selects the immutable strategy used by scheduled
scans. Leave it as `sp500-long-v0` while collecting development signals. After
reviewing the strategy and its backtest evidence, create a separate paper
version with an exact-ID confirmation:

```bash
/opt/stock-watch/.venv/bin/stock-watch-worker promote-strategy \
  --database /var/lib/stock-watch/stock-watch.db \
  --source-strategy-id sp500-long-v0 \
  --paper-strategy-id sp500-long-paper-v1 \
  --confirm-paper-trading sp500-long-paper-v1
```

The command never changes the source row. It validates its stored hash, clones
the reviewed configuration with `status=paper`, timestamps the new version,
and commits an audit event in the same transaction. Identical retries are
idempotent. Set `STOCK_WATCH_STRATEGY_ID=sp500-long-paper-v1` only after this
command succeeds, then restart `stock-watch-dispatch.timer`. Existing queued
scans retain the strategy version with which they were created.

## Activate automation

After the dashboard bootstrap, edit `/etc/stock-watch/stock-watch.env` with
paper-only Alpaca credentials and a real monitored SEC contact. Obtain and
review a current S&P 500 CSV containing symbol and CIK columns. Activation is a
separate privileged step:

```bash
sudo bash /opt/stock-watch/deploy/activate-automation-a1347-j.sh \
  /path/to/approved-sp500.csv \
  "approved source name" \
  "https://source.example/sp500.csv"
```

The third argument must be the direct HTTPS URL for CSV content with symbol and
CIK columns, not a provenance web page. Activation stores a private copy of the
supplied CSV, creates its immutable universe snapshot, refreshes Alpaca
fractional-asset metadata, verifies the
configured strategy hash plus minimum universe/CIK/asset coverage, and performs
the initial SEC refresh. Timers are enabled only if every prior step succeeds.
It does not promote a strategy; the development version records signals but
cannot create paper-order intents.

Once enabled, the universe timer checks that approved URL at 5:30 a.m. Eastern
on weekdays. It accepts only 450–550 rows with at least 95% CIK coverage and no
more than 10% symbol churn, creates a new immutable snapshot only when content
changes, and then refreshes Alpaca eligibility. A malformed, unexpectedly large,
or suspiciously different response fails the service without altering the last
known-good snapshot. The source URL is inherited from that snapshot, so changing
providers requires another explicit activation with a reviewed CSV.

## Verification

```bash
systemctl list-timers 'stock-watch-*'
systemctl status stock-watch-web.service
journalctl -u stock-watch-dispatch.service -n 50 --no-pager
journalctl -u 'stock-watch-*' --since today
curl --fail --silent http://127.0.0.1:3001/api/health
```

For a single health, service-resource, timer, and recent-error summary, run:

```bash
/opt/stock-watch/deploy/status-a1347-j.sh
```

The Operations dashboard retains meaningful command runs, live progress,
elapsed time, result context, exception cause chains, and full tracebacks.
Successful idle worker ticks remain available in the system journal but are
discarded from the database so they do not hide useful operations. Structured
JSON journal records include an `operation_id` that ties progress and errors to
the same run. Examples:

```bash
journalctl -t stock-watch-fundamentals -f -o cat
journalctl -t stock-watch-worker --since today -o cat
journalctl -u 'stock-watch-*' -p warning --since '24 hours ago'
```

## Local network access

The dashboard listens on all host interfaces at TCP port 3001 so trusted LAN
clients do not need an SSH tunnel. Find the current addresses with:

```bash
hostname -I
/opt/stock-watch/deploy/status-a1347-j.sh
```

For the current `a1347-j` address, open `http://192.168.4.45:3001`. The address
can change if DHCP does not reserve it, so reserve the host address in the
router or use working local DNS for a stable URL such as
`http://a1347-j:3001`.

There is no application login. Permit TCP 3001 only from the trusted LAN, do
not create a router port-forward, and use an authenticated HTTPS reverse proxy
or VPN before allowing access from any untrusted network.

Test a restore into a separate file; never overwrite the live database during a
restore test:

```bash
install -o stock-watch -g stock-watch -m 0600 \
  /var/backups/stock-watch/stock-watch-TIMESTAMP.db \
  /var/lib/stock-watch/restore-test.db
sudo -u stock-watch python3.12 -c \
  'import sqlite3; c=sqlite3.connect("/var/lib/stock-watch/restore-test.db"); print(c.execute("PRAGMA quick_check").fetchone()[0])'
```
