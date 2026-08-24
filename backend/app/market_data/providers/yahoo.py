"""Yahoo Finance history provider for the FX reference markets.

Scope
-----
This serves candles for EUR/USD and USD/JPY only. Binance has no FX market, so
there is no exchange-native option for them, and they exist purely as a cost
control for the crypto studies (see ``app/market_data/reference_markets.py``).

Everything tradable still comes from Binance. That rule is not relaxed here: it
is precisely because these two markets are *not* tradable that a second-hand,
undocumented source is acceptable for them.

Limits worth knowing
--------------------
Yahoo caps intraday history hard, and silently: asking for a year of 15 minute
candles returns 60 days without complaining. :data:`MAX_RANGE` records the real
limits so the caller can warn instead of quietly backtesting a shorter window
than it asked for.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.constants import timeframe_to_ms
from app.core.logging import get_logger

logger = get_logger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

#: Our timeframe -> Yahoo interval. Yahoo has no 2h, 6h, 8h or 12h bar.
INTERVALS: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "1d",
    "1w": "1wk",
}

#: How far back each interval can actually go, in days. Yahoo enforces these.
MAX_RANGE_DAYS: dict[str, int] = {
    "1m": 7,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "1h": 730,
    "1d": 10_000,
    "1w": 10_000,
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def supports(timeframe: str) -> bool:
    return timeframe in INTERVALS


def max_history_days(timeframe: str) -> int:
    return MAX_RANGE_DAYS.get(timeframe, 0)


class YahooHistoryProvider:
    """Fetches OHLCV in the same shape a gateway returns it.

    ``fetch_ohlcv`` deliberately mirrors
    :meth:`app.exchange.base.ExchangeGateway.fetch_ohlcv` so the market data
    service can dispatch to either without special-casing the caller.
    """

    name = "yahoo"

    def __init__(self, timeout_seconds: float = 25.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.last_error: str | None = None

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int | None = None,
        limit: int = 1000,
    ) -> list[list[float]]:
        """Return ``[open_time_ms, open, high, low, close, volume]`` rows."""
        from app.market_data import reference_markets

        market = reference_markets.get(symbol)
        provider_symbol = market.provider_symbol if market else symbol.replace("/", "") + "=X"

        interval = INTERVALS.get(timeframe)
        if interval is None:
            raise ValueError(f"Yahoo has no {timeframe} bar. Available: {', '.join(INTERVALS)}")

        params: dict[str, Any] = {"interval": interval, "includePrePost": "false"}
        if since_ms:
            params["period1"] = int(since_ms // 1000)
            params["period2"] = int((since_ms + limit * timeframe_to_ms(timeframe)) // 1000)
        else:
            params["range"] = f"{min(max_history_days(timeframe), 730)}d"

        url = CHART_URL.format(symbol=provider_symbol)
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=_HEADERS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

        return self._parse(payload)

    @staticmethod
    def _parse(payload: dict[str, Any]) -> list[list[float]]:
        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise RuntimeError(str(chart["error"])[:200])
        results = chart.get("result") or []
        if not results:
            return []

        result = results[0]
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        rows: list[list[float]] = []
        for index, timestamp in enumerate(timestamps):
            open_ = _at(opens, index)
            high = _at(highs, index)
            low = _at(lows, index)
            close = _at(closes, index)
            # Yahoo pads closed sessions with null OHLC. Carrying those through
            # would create flat zero-range bars that quietly break ATR and every
            # range based indicator, so they are dropped instead.
            if None in (open_, high, low, close):
                continue
            rows.append(
                [
                    float(int(timestamp) * 1000),
                    float(open_),
                    float(high),
                    float(low),
                    float(close),
                    float(_at(volumes, index) or 0.0),
                ]
            )
        return rows


def _at(values: list[Any], index: int) -> Any:
    try:
        return values[index]
    except IndexError:
        return None
