"""SEC EDGAR submissions and XBRL company-facts client."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Mapping

from ..http import HttpTransport, UrllibTransport, require_success


SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_FILES_BASE_URL = "https://www.sec.gov"
ResponseObserver = Callable[[str, Mapping[str, str], Any], None]


class MinimumIntervalLimiter:
    """Thread-safe limiter that spaces requests by a minimum interval."""

    def __init__(
        self,
        requests_per_second: float = 8.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0 or requests_per_second > 10:
            raise ValueError("SEC request rate must be between 0 and 10 per second")
        self._minimum_interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleeper = sleeper
        self._last_request: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request is not None:
                remaining = self._minimum_interval - (now - self._last_request)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request = now


class SecClient:
    def __init__(
        self,
        *,
        user_agent: str,
        transport: HttpTransport | None = None,
        limiter: MinimumIntervalLimiter | None = None,
        response_observer: ResponseObserver | None = None,
    ) -> None:
        if not user_agent.strip() or "@" not in user_agent:
            raise ValueError("SEC user agent must identify the application and email")
        self._user_agent = user_agent
        self._transport = transport or UrllibTransport()
        self._limiter = limiter or MinimumIntervalLimiter()
        self._response_observer = response_observer

    @classmethod
    def from_environment(
        cls,
        *,
        transport: HttpTransport | None = None,
        limiter: MinimumIntervalLimiter | None = None,
        response_observer: ResponseObserver | None = None,
    ) -> "SecClient":
        user_agent = os.environ.get("SEC_USER_AGENT", "")
        if not user_agent:
            raise ValueError("SEC_USER_AGENT is required")
        return cls(
            user_agent=user_agent,
            transport=transport,
            limiter=limiter,
            response_observer=response_observer,
        )

    def get_company_tickers(self) -> Mapping[str, Any]:
        return self._get(f"{SEC_FILES_BASE_URL}/files/company_tickers.json")

    def get_submissions(self, cik: str | int) -> Mapping[str, Any]:
        padded = _normalize_cik(cik)
        return self._get(f"{SEC_DATA_BASE_URL}/submissions/CIK{padded}.json")

    def get_company_facts(self, cik: str | int) -> Mapping[str, Any]:
        padded = _normalize_cik(cik)
        return self._get(
            f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK{padded}.json"
        )

    def _get(self, url: str) -> Mapping[str, Any]:
        if not (
            url.startswith(f"{SEC_DATA_BASE_URL}/")
            or url.startswith(f"{SEC_FILES_BASE_URL}/")
        ):
            raise ValueError("SEC URL is outside the allowlist")
        self._limiter.wait()
        response = self._transport.request(
            "GET",
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": self._user_agent,
            },
            timeout=30,
        )
        data = require_success("sec", response)
        if not isinstance(data, dict):
            raise ValueError("SEC response is malformed")
        if self._response_observer is not None:
            self._response_observer(url, {}, data)
        return data


def _normalize_cik(cik: str | int) -> str:
    value = str(cik).strip()
    if not value.isdigit() or len(value) > 10:
        raise ValueError("CIK must contain at most ten digits")
    return value.zfill(10)
