from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from stock_watch_worker.http import HttpResponse


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout: float


class FakeTransport:
    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.requests: list[RecordedRequest] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        self.requests.append(
            RecordedRequest(method, url, dict(headers or {}), body, timeout)
        )
        if not self.responses:
            raise AssertionError("fake transport has no queued response")
        return self.responses.pop(0)


def json_response(data: object, status: int = 200) -> HttpResponse:
    return HttpResponse(
        status=status,
        headers={"Content-Type": "application/json"},
        body=json.dumps(data).encode("utf-8"),
    )
