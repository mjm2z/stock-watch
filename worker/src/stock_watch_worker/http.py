"""Minimal injectable HTTP transport for provider clients."""

from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            body = _decode_content(self.body, self.headers)
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, zlib.error) as error:
            raise ValueError("provider returned invalid JSON") from error


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse: ...


class UrllibTransport:
    """Standard-library transport; network behavior remains easy to fake."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers or {}),
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                status=error.code,
                headers=dict(error.headers.items()) if error.headers else {},
                body=error.read(),
            )


class ProviderError(RuntimeError):
    def __init__(
        self,
        provider: str,
        status: int,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(f"{provider} request failed ({status}): {message}")
        self.provider = provider
        self.status = status
        self.retryable = retryable


def _decode_content(body: bytes, headers: Mapping[str, str]) -> bytes:
    encoding = next(
        (value for key, value in headers.items() if key.lower() == "content-encoding"),
        "",
    ).strip().lower()
    if not encoding or encoding == "identity":
        return body
    if encoding == "gzip":
        return gzip.decompress(body)
    if encoding == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    raise ValueError(f"provider returned unsupported content encoding: {encoding}")


def require_success(provider: str, response: HttpResponse) -> Any:
    try:
        data = response.json()
    except ValueError:
        if 200 <= response.status < 300:
            raise
        raise ProviderError(
            provider,
            response.status,
            "provider returned a non-JSON error response",
            retryable=response.status == 429 or response.status >= 500,
        ) from None
    if 200 <= response.status < 300:
        return data

    message = "unknown provider error"
    if isinstance(data, dict):
        raw_message = data.get("message") or data.get("error")
        if isinstance(raw_message, str):
            message = raw_message
    raise ProviderError(
        provider,
        response.status,
        message,
        retryable=response.status == 429 or response.status >= 500,
    )
