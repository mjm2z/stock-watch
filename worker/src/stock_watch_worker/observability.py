"""Structured journal logging and durable CLI operation telemetry."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, TextIO

from .database import connect


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OperationMonitor:
    def __init__(
        self,
        *,
        database: Path,
        command: str,
        context: Mapping[str, Any],
        output: TextIO = sys.stdout,
    ) -> None:
        self.id = f"operation-{uuid.uuid4()}"
        self.database = database
        self.command = command
        self.context = _json_safe_mapping(context)
        self.output = output
        self._connection: sqlite3.Connection | None = None
        self._started_monotonic = time.monotonic()
        self._discard_success = False
        self._result: dict[str, Any] = {}
        self._summary_message = "operation completed"
        self._failed = False

    def start(self) -> None:
        started_at = _utc_iso(utc_now())
        self._open_telemetry_connection()
        if self._connection is not None:
            try:
                with self._connection:
                    self._connection.execute(
                        """
                        DELETE FROM operation_runs
                        WHERE status != 'running'
                          AND julianday(completed_at) < julianday('now', '-30 days')
                        """
                    )
                    self._connection.execute(
                        """
                        INSERT INTO operation_runs(
                            id, command, status, started_at, heartbeat_at,
                            message, context_json, host, process_id
                        ) VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self.id,
                            self.command,
                            started_at,
                            started_at,
                            "operation started",
                            _canonical_json(self.context),
                            socket.gethostname(),
                            os.getpid(),
                        ),
                    )
            except sqlite3.Error as error:
                self._disable_persistence(error)
        self.event("info", "operation_started", "operation started")

    def progress(
        self,
        current: int,
        total: int,
        message: str,
        **context: Any,
    ) -> None:
        if current < 0 or total < 1 or current > total:
            raise ValueError("operation progress values are invalid")
        self.event(
            "info",
            "operation_progress",
            message,
            current=current,
            total=total,
            context=context,
        )

    def result(self, message: str, **values: Any) -> None:
        self._result.update(_json_safe_mapping(values))
        self._summary_message = message
        self.event("info", "operation_result", message, context=values)

    def discard_on_success(self) -> None:
        self._discard_success = True

    def event(
        self,
        level: str,
        event: str,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        occurred_at = _utc_iso(utc_now())
        safe_context = _json_safe_mapping(context or {})
        record = {
            "timestamp": occurred_at,
            "level": level,
            "operation_id": self.id,
            "command": self.command,
            "event": event,
            "message": message,
            "progress": (
                {"current": current, "total": total}
                if current is not None and total is not None
                else None
            ),
            "context": safe_context,
        }
        print(_canonical_json(record), file=self.output, flush=True)
        if self._connection is None:
            return
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO operation_events(
                        operation_run_id, occurred_at, level, event, message,
                        progress_current, progress_total, context_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.id,
                        occurred_at,
                        level,
                        event,
                        message,
                        current,
                        total,
                        _canonical_json(safe_context),
                    ),
                )
                self._connection.execute(
                    """
                    UPDATE operation_runs
                    SET heartbeat_at = ?,
                        progress_current = COALESCE(?, progress_current),
                        progress_total = COALESCE(?, progress_total),
                        message = ?
                    WHERE id = ?
                    """,
                    (occurred_at, current, total, message, self.id),
                )
        except sqlite3.Error as error:
            self._disable_persistence(error)

    def complete(self) -> None:
        if self._failed:
            return
        elapsed = time.monotonic() - self._started_monotonic
        self.event(
            "info",
            "operation_succeeded",
            self._summary_message,
            context={"elapsed_seconds": round(elapsed, 3), **self._result},
        )
        if self._connection is None:
            return
        try:
            with self._connection:
                if self._discard_success:
                    self._connection.execute(
                        "DELETE FROM operation_runs WHERE id = ?", (self.id,)
                    )
                else:
                    self._connection.execute(
                        """
                        UPDATE operation_runs
                        SET status = 'succeeded', completed_at = ?, heartbeat_at = ?,
                            message = ?, result_json = ?
                        WHERE id = ?
                        """,
                        (
                            _utc_iso(utc_now()),
                            _utc_iso(utc_now()),
                            self._summary_message,
                            _canonical_json(self._result),
                            self.id,
                        ),
                    )
        except sqlite3.Error as error:
            self._disable_persistence(error)

    def fail(self, error: BaseException) -> None:
        self._failed = True
        elapsed = time.monotonic() - self._started_monotonic
        chain = exception_chain(error)
        formatted_traceback = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        self.event(
            "error",
            "operation_failed",
            str(error) or type(error).__name__,
            context={
                "elapsed_seconds": round(elapsed, 3),
                "error_type": type(error).__name__,
                "exception_chain": chain,
                "traceback": formatted_traceback,
            },
        )
        if self._connection is not None:
            completed_at = _utc_iso(utc_now())
            try:
                with self._connection:
                    self._connection.execute(
                    """
                    UPDATE operation_runs
                    SET status = 'failed', completed_at = ?, heartbeat_at = ?,
                        message = ?, error_type = ?, error_message = ?,
                        exception_chain_json = ?, traceback = ?, result_json = ?
                    WHERE id = ?
                    """,
                    (
                        completed_at,
                        completed_at,
                        "operation failed",
                        type(error).__name__,
                        str(error),
                        _canonical_json(chain),
                        formatted_traceback,
                        _canonical_json(self._result),
                        self.id,
                    ),
                    )
            except sqlite3.Error as persistence_error:
                self._disable_persistence(persistence_error)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _open_telemetry_connection(self) -> None:
        if not self.database.exists():
            return
        connection = connect(self.database)
        table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'operation_runs'
            """
        ).fetchone()
        if table is None:
            connection.close()
            return
        self._connection = connection

    def _disable_persistence(self, error: sqlite3.Error) -> None:
        warning = {
            "timestamp": _utc_iso(utc_now()),
            "level": "warning",
            "operation_id": self.id,
            "command": self.command,
            "event": "telemetry_persistence_disabled",
            "message": str(error),
        }
        print(_canonical_json(warning), file=sys.stderr, flush=True)
        self.close()


@contextmanager
def monitor_cli_operation(args: argparse.Namespace) -> Iterator[OperationMonitor]:
    monitor = OperationMonitor(
        database=Path(args.database),
        command=str(args.command),
        context={
            key: value
            for key, value in vars(args).items()
            if key not in {"command", "database"}
        },
    )
    monitor.start()
    try:
        yield monitor
    except BaseException as error:
        monitor.fail(error)
        raise
    else:
        monitor.complete()
    finally:
        monitor.close()


def exception_chain(error: BaseException) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        values.append(
            {
                "type": type(current).__name__,
                "message": str(current) or type(current).__name__,
            }
        )
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return values


def _json_safe_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe(value) for key, value in values.items()}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
