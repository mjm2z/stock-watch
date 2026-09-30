"""Register verified StockWatch component endpoints in existing HomeOps configuration.

Run as the HomeOps user on a1347-m after installation/configuration. This script
requires each endpoint healthy first, preserves unrelated settings, backs up the
original, and updates atomically. a1347-j remains the independent watchdog.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
from urllib.request import urlopen


COMPONENTS = ("market-feed", "execution", "notifications")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--components", nargs="+", choices=COMPONENTS, default=COMPONENTS,
                        help="Register ready components independently; default: all three")
    args = parser.parse_args()
    if socket.gethostname().split(".")[0] != "a1347-m":
        raise SystemExit("Run on a1347-m")
    path = Path.home() / ".config/home-ops/server.json"
    original = path.read_bytes()
    config = json.loads(original)
    existing = {s["id"]: s for s in config["sites"]}
    added = []
    for component in dict.fromkeys(args.components):
        url = "http://192.168.4.35:3001/api/health/" + component
        with urlopen(url, timeout=5) as response:
            body = json.load(response)
            healthy = (body.get("fresh") is True and body.get("retention", {}).get("healthy") is True
                       if component == "market-feed" else body.get("healthy") is True)
            if response.status != 200 or not healthy:
                raise RuntimeError(component + " is not ready")
        identifier = "stock-watch-" + component
        if identifier in existing and existing[identifier].get("url") != url:
            raise RuntimeError("Existing component URL differs; review " + identifier)
        desired = {
                    "id": identifier,
                    "name": "StockWatch " + component,
                    "machine": "a1347-m",
                    "url": url,
                    "kind": "API",
                    "parent_site": "stock-watch",
                    "open_url": "http://stockwatch.home.arpa:3001/crypto?view=operations",
                }
        if identifier not in existing:
            config["sites"].append(desired)
            added.append(component)
        elif any(existing[identifier].get(key) != value for key, value in desired.items()) or existing[identifier].get("page_url") == url:
            existing[identifier].update(desired)
            if existing[identifier].get("page_url") == url:
                del existing[identifier]["page_url"]
            added.append(component)
    if not added:
        print("Selected healthy components are already registered; no configuration changed.")
        return
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
        "Registered healthy StockWatch components: " + ", ".join(added)
        + ". Restart home-ops.service and home-ops-network.service, then verify a1347-j reporting."
    )


if __name__ == "__main__":
    main()
