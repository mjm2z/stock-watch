"""One Bitcoin coordinator owner; feed events wake exits, bars still govern entries."""

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import threading
import time
from urllib.request import urlopen
from ..database import connect
from .broker import CryptoBroker
from .coordinator import tick
from .history import connect_history
from .automation_data import health
from .engine import instant


class ExecutionBroker(CryptoBroker):
    def quote(self, now):
        now = datetime.now(timezone.utc)
        result = super().quote(now)
        if not 0 <= (now - instant(result["t"])).total_seconds() <= 5:
            raise ValueError("Execution quote exceeds five seconds")
        return result


def feed_wake(event, latest, stop):
    while not stop.is_set():
        try:
            with urlopen("http://127.0.0.1:3012/events", timeout=10) as response:
                for raw in response:
                    if stop.is_set():
                        return
                    if not raw.startswith(b"data: "):
                        continue
                    snapshot = json.loads(raw[6:])
                    previous = latest.get("snapshot", {})
                    latest["snapshot"] = snapshot
                    if snapshot.get("fresh") and snapshot.get("price") != previous.get(
                        "price"
                    ):
                        event.set()
                    elif not snapshot.get("fresh"):
                        event.clear()
        except Exception:
            latest["snapshot"] = {"fresh": False}
            event.clear()
            stop.wait(1)


def run(path):
    # Same lock as legacy CLI tick/activation paths. Nonblocking ownership fails visibly.
    with Path(str(path) + ".systems-tick.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = connect(path)
        history = connect_history(str(path) + ".bitcoin-history.db")
        broker = ExecutionBroker()
        wake = threading.Event()
        stop = threading.Event()
        latest = {}
        threading.Thread(
            target=feed_wake, args=(wake, latest, stop), daemon=True
        ).start()
        next_decision = 0.0
        next_periodic = 0.0
        last_dispatch = 0.0
        try:
            while True:
                now_mono = time.monotonic()
                if now_mono < next_periodic and not wake.is_set():
                    wake.wait(min(1, next_periodic - now_mono))
                    continue
                # At most one evaluation per two seconds, independent of display delivery.
                if now_mono - last_dispatch < 2:
                    stop.wait(2 - (now_mono - last_dispatch))
                    continue
                wake.clear()
                now = datetime.now(timezone.utc)
                decisions = now_mono >= next_decision
                observation = dict(latest.get("snapshot", {}))
                if not decisions and now_mono < next_periodic:
                    receipt = observation.get("receivedAt", 0) / 1000
                    heartbeat = observation.get("heartbeatAt", 0) / 1000
                    if (
                        not observation.get("fresh")
                        or not 0 <= time.time() - receipt <= 5
                        or not 0 <= time.time() - heartbeat <= 3
                    ):
                        continue
                try:
                    tick(
                        db,
                        history,
                        broker,
                        now,
                        exits_only=not decisions,
                        observation=observation,
                    )
                    health(db, "execution_owner", now)
                except Exception as error:
                    health(db, "execution_owner", now, str(error)[:300])
                last_dispatch = time.monotonic()
                next_periodic = last_dispatch + 10
                if decisions:
                    next_decision = last_dispatch + 30
        finally:
            stop.set()
            db.close()
            history.close()


if __name__ == "__main__":
    run(os.environ["STOCK_WATCH_DATABASE_PATH"])
