from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class DeployContractTests(unittest.TestCase):
    def test_dispatcher_uses_explicit_configured_strategy_version(self) -> None:
        environment = (REPOSITORY_ROOT / "deploy/stock-watch.env.example").read_text(
            encoding="utf-8"
        )
        service = (
            REPOSITORY_ROOT / "deploy/systemd/stock-watch-dispatch.service"
        ).read_text(encoding="utf-8")

        self.assertIn("STOCK_WATCH_STRATEGY_ID=sp500-long-v0", environment)
        self.assertIn("--strategy-id ${STOCK_WATCH_STRATEGY_ID}", service)

    def test_web_sandbox_allows_sqlite_wal_state_but_client_is_read_only(self) -> None:
        service = (
            REPOSITORY_ROOT / "deploy/systemd/stock-watch-web.service"
        ).read_text(encoding="utf-8")
        dashboard = (REPOSITORY_ROOT / "lib/worker-dashboard.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "ReadWritePaths=/opt/stock-watch/.next/cache /var/lib/stock-watch",
            service,
        )
        self.assertIn("new DatabaseSync(path, { readOnly: true })", dashboard)
        self.assertIn("PRAGMA query_only = ON", dashboard)

    def test_web_listens_on_the_trusted_lan_and_status_reports_addresses(self) -> None:
        service = (
            REPOSITORY_ROOT / "deploy/systemd/stock-watch-web.service"
        ).read_text(encoding="utf-8")
        status = (REPOSITORY_ROOT / "deploy/status-a1347-j.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("--hostname 0.0.0.0 --port 3001", service)
        self.assertNotIn("--hostname 127.0.0.1", service)
        self.assertIn("hostname -I", status)
        self.assertIn('http://${address}:${DASHBOARD_PORT}', status)

    def test_bootstrap_pins_node_and_leaves_worker_timers_disabled(self) -> None:
        bootstrap = (REPOSITORY_ROOT / "deploy/bootstrap-a1347-j.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('readonly NODE_VERSION="24.16.0"', bootstrap)
        self.assertIn(
            'readonly NODE_SHA256="d804845d34eddc21dc1092b519d643ef40b1f58ec5dec5c22b1f4bd8fabde6c9"',
            bootstrap,
        )
        self.assertIn("systemctl enable --now stock-watch-web.service", bootstrap)
        self.assertNotIn("systemctl enable --now stock-watch-worker.timer", bootstrap)
        self.assertIn("apt-get install -y python3.12-venv", bootstrap)
        self.assertIn('python3.12 -m venv --clear "${INSTALL_ROOT}/.venv"', bootstrap)
        self.assertIn(
            '--strategy "${INSTALL_ROOT}/worker/config/strategy-v0.json"', bootstrap
        )

    def test_activation_is_readiness_gated_and_never_promotes(self) -> None:
        activation = (
            REPOSITORY_ROOT / "deploy/activate-automation-a1347-j.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("systemctl start stock-watch-assets.service", activation)
        self.assertIn("deployment-check", activation)
        self.assertIn("--minimum-cik-coverage 0.95", activation)
        self.assertIn("sync-universe", activation)
        self.assertNotIn("=(|replace_)", activation)
        self.assertIn("grep -Eq '^ALPACA_API_KEY_ID=replace_'", activation)
        self.assertIn("grep -Eq '^ALPACA_API_SECRET_KEY=replace_'", activation)
        self.assertIn("systemctl enable --now", activation)
        self.assertIn("stock-watch-universe.timer", activation)
        self.assertNotIn("promote-strategy", activation)

    def test_daily_universe_sync_is_https_sourced_and_change_gated(self) -> None:
        service = (
            REPOSITORY_ROOT / "deploy/systemd/stock-watch-universe.service"
        ).read_text(encoding="utf-8")
        timer = (
            REPOSITORY_ROOT / "deploy/systemd/stock-watch-universe.timer"
        ).read_text(encoding="utf-8")
        activation = (
            REPOSITORY_ROOT / "deploy/activate-automation-a1347-j.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("sync-universe", service)
        self.assertIn("refresh-assets", service)
        self.assertIn("05:30:00 America/New_York", timer)
        self.assertIn('^https://', activation)

    def test_worker_services_emit_unbuffered_identified_journal_logs(self) -> None:
        services = (
            "stock-watch-assets.service",
            "stock-watch-backup.service",
            "stock-watch-dispatch.service",
            "stock-watch-fundamentals.service",
            "stock-watch-maintenance.service",
            "stock-watch-universe.service",
            "stock-watch-worker.service",
        )
        for filename in services:
            service = (REPOSITORY_ROOT / "deploy/systemd" / filename).read_text(
                encoding="utf-8"
            )
            self.assertIn("Environment=PYTHONUNBUFFERED=1", service)
            self.assertIn("StandardOutput=journal", service)
            self.assertIn("StandardError=journal", service)
            self.assertIn("SyslogIdentifier=stock-watch-", service)

    def test_status_script_reports_health_timers_resources_and_errors(self) -> None:
        status = (REPOSITORY_ROOT / "deploy/status-a1347-j.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("/api/health", status)
        self.assertIn("MemoryPeak", status)
        self.assertIn("systemctl list-timers", status)
        self.assertIn("--priority=warning", status)

    def test_update_quiesces_services_and_restores_only_enabled_timers(self) -> None:
        update = (REPOSITORY_ROOT / "deploy/update-a1347-j.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("systemctl is-enabled --quiet", update)
        self.assertIn('systemctl stop "${TIMER_UNITS[@]}"', update)
        self.assertIn("stock-watch-web.service", update)
        self.assertIn("bootstrap-a1347-j.sh", update)
        self.assertIn('systemctl enable --now "${enabled_timers[@]}"', update)
        self.assertIn("/api/health", update)


if __name__ == "__main__":
    unittest.main()
