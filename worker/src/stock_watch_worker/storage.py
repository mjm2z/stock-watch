"""Content-addressed immutable raw-data landing store."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class StoredObject:
    path: Path
    sha256: str
    bytes_written: int
    already_existed: bool


class ContentAddressedStore:
    """Store raw JSON once without allowing silent mutation."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def put_json(
        self,
        *,
        dataset: str,
        provider: str,
        logical_key: str,
        payload: Any,
        captured_at: datetime | None = None,
    ) -> StoredObject:
        captured = captured_at or datetime.now(timezone.utc)
        if captured.tzinfo is None:
            raise ValueError("captured_at must be timezone aware")

        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical_payload).hexdigest()
        dataset_component = _safe_component(dataset)
        provider_component = _safe_component(provider)
        key_component = _safe_component(logical_key)
        relative = Path(
            "raw",
            dataset_component,
            provider_component,
            captured.strftime("%Y"),
            captured.strftime("%m"),
            captured.strftime("%d"),
            f"{key_component}-{digest}.json.gz",
        )
        destination = self.root / relative
        if destination.exists():
            return StoredObject(
                path=destination,
                sha256=digest,
                bytes_written=destination.stat().st_size,
                already_existed=True,
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "captured_at": captured.astimezone(timezone.utc).isoformat(),
            "dataset": dataset,
            "logical_key": logical_key,
            "payload": payload,
            "payload_sha256": digest,
            "provider": provider,
        }
        encoded = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                with gzip.GzipFile(fileobj=temporary, mode="wb", mtime=0) as archive:
                    archive.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, destination)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

        return StoredObject(
            path=destination,
            sha256=digest,
            bytes_written=destination.stat().st_size,
            already_existed=False,
        )


def read_stored_json(path: str | Path) -> Any:
    with gzip.open(path, mode="rt", encoding="utf-8") as archive:
        return json.load(archive)


def _safe_component(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("storage path components cannot be empty")
    component = SAFE_COMPONENT.sub("-", stripped).strip(".-")
    if not component:
        raise ValueError("storage path component has no safe characters")
    return component[:120]
