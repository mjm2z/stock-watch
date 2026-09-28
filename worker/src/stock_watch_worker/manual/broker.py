"""Fixed paper endpoints and labelled IEX stock quotes; no margin sizing."""

from datetime import datetime, timezone
import os
from urllib.parse import quote, urlencode
from ..systems.broker import CryptoBroker
from ..systems.engine import instant
from .store import money


class ManualBroker(CryptoBroker):
    def __init__(self, asset):
        key = os.environ.get("MANUAL_ALPACA_API_KEY_ID")
        secret = os.environ.get("MANUAL_ALPACA_API_SECRET_KEY")
        if not key or not secret:
            raise ValueError("Manual paper credentials are not configured")
        super().__init__(
            key=key,
            secret=secret,
        )
        self.asset = asset
        self.quotes_cache = {}
        self.clock_cache = None

    def metadata(self, symbol):
        return self.request("GET", "/v2/assets/" + quote(symbol, safe=""))

    def quote(self, symbol):
        now = datetime.now(timezone.utc)
        if self.asset == "bitcoin":
            value = self.request(
                "GET",
                "/v1beta3/crypto/us/latest/quotes?" + urlencode({"symbols": symbol}),
                data=True,
            )["quotes"][symbol]
            source = "Alpaca US crypto"
        else:
            value = self.quotes_cache.get(symbol)
            if value is None:
                value = self.request(
                    "GET",
                    "/v2/stocks/quotes/latest?"
                    + urlencode({"symbols": symbol, "feed": "iex"}),
                    data=True,
                )["quotes"][symbol]
            source = "Alpaca IEX (not consolidated SIP)"
        if not 0 <= (now - instant(value["t"])).total_seconds() <= 5 or money(
            value["ap"]
        ) < money(value["bp"]):
            raise ValueError(
                "Fresh uncrossed executable quote required (maximum five seconds)"
            )
        return {
            "ask": str(value["ap"]),
            "bid": str(value["bp"]),
            "at": value["t"],
            "source": source,
        }

    def submit_request(self, request):
        return self.request("POST", "/v2/orders", request)

    def batch_quotes(self, symbols):
        self.quotes_cache = {}
        self.clock_cache = bool(self.request("GET", "/v2/clock")["is_open"])
        if not self.clock_cache:
            return
        symbols = sorted(set(symbols))
        for offset in range(0, len(symbols), 100):
            self.quotes_cache.update(
                self.request(
                    "GET",
                    "/v2/stocks/quotes/latest?"
                    + urlencode(
                        {
                            "symbols": ",".join(symbols[offset : offset + 100]),
                            "feed": "iex",
                        }
                    ),
                    data=True,
                )["quotes"]
            )

    def market_open(self):
        return self.asset == "bitcoin" or (
            self.clock_cache
            if self.clock_cache is not None
            else bool(self.request("GET", "/v2/clock")["is_open"])
        )
