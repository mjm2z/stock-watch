"""Register verified StockWatch component endpoints in existing HomeOps configuration.

Run as the HomeOps user on a1347-m after installation/configuration. This script
requires each endpoint healthy first, preserves unrelated settings, backs up the
original, and updates atomically. a1347-j remains the independent watchdog.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
from urllib.request import urlopen


def main():
    if socket.gethostname().split(".")[0] != "a1347-m":
        raise SystemExit("Run on a1347-m")
    path = Path.home() / ".config/home-ops/server.json"
    original = path.read_bytes()
    config = json.loads(original)
    existing = {s["id"] for s in config["sites"]}
    for component in ("market-feed", "execution", "notifications"):
        url = "http://192.168.4.35:3001/api/health/" + component
        with urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(component + " is not ready")
        identifier = "stock-watch-" + component
        if identifier not in existing:
            config["sites"].append(
                {
                    "id": identifier,
                    "name": "StockWatch " + component,
                    "machine": "a1347-m",
                    "url": url,
                    "kind": "Website",
                    "open_url": "http://stockwatch.home.arpa:3001/crypto?view=operations",
                    "page_url": url,
                }
            )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(path.name + ".before-live-paper-" + stamp)
    with backup.open("xb") as stream:
        stream.write(original)
    backup.chmod(0o600)
    temporary = path.with_name(path.name + ".live-paper-new")
    with temporary.open("x") as stream:
        json.dump(config, stream, indent=2)
    temporary.chmod(0o600)
    if path.read_bytes() != original:
        raise RuntimeError("Config changed concurrently; review staged file")
    os.replace(temporary, path)
    print(
        "Registered three healthy StockWatch components. Restart HomeOps through its existing service workflow and verify a1347-j reporting."
    )


if __name__ == "__main__":
    main()
