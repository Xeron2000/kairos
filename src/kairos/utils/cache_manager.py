"""Minimal price cache with TTL-based expiration."""

from __future__ import annotations

import time


class PriceCache:
    """TTL-based price cache. Only get_prices and set_price are used."""

    def __init__(self, max_len: int = 1000, max_age_seconds: int = 300) -> None:
        self._dict: dict[str, tuple[float, float]] = {}  # symbol -> (price, expiry_ts)

    def get_prices(self, symbols: list[str], default: float | None = None) -> dict[str, float | None]:
        now = time.time()
        result: dict[str, float | None] = {}
        for sym in symbols:
            entry = self._dict.get(sym)
            if entry is not None and entry[1] > now:
                result[sym] = entry[0]
            else:
                result[sym] = default
        return result

    def set_price(self, symbol: str, price: float) -> None:
        self._dict[symbol] = (price, time.time() + 300)


price_cache = PriceCache()
