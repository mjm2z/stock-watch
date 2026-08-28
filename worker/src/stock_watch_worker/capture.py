"""Adapters that capture decoded provider responses before transformation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .storage import ContentAddressedStore, StoredObject


class JsonResponseCapture:
    def __init__(
        self,
        store: ContentAddressedStore,
        *,
        provider: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.captures: list[StoredObject] = []

    def __call__(
        self,
        path: str,
        params: Mapping[str, str],
        payload: Any,
    ) -> None:
        canonical_params = json.dumps(
            dict(params), sort_keys=True, separators=(",", ":")
        )
        request_hash = hashlib.sha256(canonical_params.encode("utf-8")).hexdigest()[:16]
        dataset = path.strip("/").replace("/", "-") or "root"
        logical_key = f"request-{request_hash}"
        stored = self._store.put_json(
            dataset=dataset,
            provider=self._provider,
            logical_key=logical_key,
            payload=payload,
            captured_at=self._clock(),
        )
        self.captures.append(stored)
