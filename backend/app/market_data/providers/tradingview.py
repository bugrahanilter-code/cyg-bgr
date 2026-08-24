"""TradingView market-context provider.

What this is
------------
TradingView powers its public crypto screener with a JSON endpoint at
``scanner.tradingview.com``. This provider calls that endpoint to enrich the
market browser with columns Binance does not publish: TradingView's own
technical rating, RSI, ATR, relative volume and the 52 week range.

What this deliberately is NOT
-----------------------------
A candle source. TradingView does not publish a documented OHLCV API; the only
way to pull history is to reverse-engineer the private websocket their charts
use, which needs an account, breaks without notice and is not something to build
a backtest on. It would also be pointless: TradingView's ``BINANCE:BTCUSDT.P``
series *is* Binance's data, relayed. Taking it second-hand would add latency and
a fragile dependency in exchange for identical numbers.

So the split is:

* candles for strategies and backtests -> Binance (official, rate limited, exact)
* screener context for the market browser -> TradingView (this file)
* charts in the dashboard -> TradingView's own embedded widget

The endpoint is undocumented, so every call is defensive: a failure downgrades
the market browser to Binance-only data and never breaks a page.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.logging import get_logger
from app.market_data.providers.base import MarketStats

logger = get_logger(__name__)

SCANNER_URL = "https://scanner.tradingview.com/crypto/scan"

#: Screener columns requested for every market, in order.
COLUMNS: tuple[str, ...] = (
    "name",
    "close",
    "change",
    "change_abs",
    "high",
    "low",
    "volume",
    "Recommend.All",
    "Recommend.MA",
    "Recommend.Other",
    "RSI",
    "ATR",
    "relative_volume_10d_calc",
    "Volatility.D",
    "average_volume_10d_calc",
)

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


def rating_label(score: float | None) -> str:
    """Translate TradingView's numeric rating into its published wording."""
    if score is None:
        return "UNKNOWN"
    if score >= 0.5:
        return "STRONG_BUY"
    if score >= 0.1:
        return "BUY"
    if score > -0.1:
        return "NEUTRAL"
    if score > -0.5:
        return "SELL"
    return "STRONG_SELL"


def to_tradingview_symbol(symbol: str, market_type: str = "futures") -> str:
    """``BTC/USDT`` -> ``BINANCE:BTCUSDT.P`` (perpetual) or ``BINANCE:BTCUSDT``.

    The ``.P`` suffix is how TradingView distinguishes a perpetual future from
    the spot pair of the same name.
    """
    compact = symbol.split(":")[0].replace("/", "").upper()
    suffix = ".P" if str(market_type).lower() == "futures" else ""
    return f"BINANCE:{compact}{suffix}"


def from_tradingview_symbol(tv_symbol: str) -> str:
    """``BINANCE:BTCUSDT.P`` -> ``BTC/USDT`` (best effort)."""
    body = tv_symbol.split(":")[-1]
    if body.endswith(".P"):
        body = body[:-2]
    for quote in ("USDT", "USDC", "FDUSD", "BUSD", "TRY", "BTC", "ETH", "BNB"):
        if body.endswith(quote) and len(body) > len(quote):
            return f"{body[: -len(quote)]}/{quote}"
    return body


class TradingViewProvider:
    """Reads the public TradingView crypto screener.

    Results are cached for ``ttl_seconds`` because the market browser polls and
    the endpoint is a courtesy, not a contract we pay for.
    """

    name = "tradingview"

    def __init__(
        self,
        exchange: str = "BINANCE",
        market_type: str = "futures",
        timeout_seconds: float = 20.0,
        ttl_seconds: float = 300.0,
        page_size: int = 500,
    ) -> None:
        self.exchange = exchange
        self.market_type = market_type
        self.timeout_seconds = timeout_seconds
        self.ttl_seconds = ttl_seconds
        self.page_size = page_size
        self._cache: dict[str, MarketStats] = {}
        self._cached_at: float = 0.0
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    # -- public API ---------------------------------------------------------
    async def fetch_context(self, symbols: list[str] | None = None) -> dict[str, MarketStats]:
        """Return screener context keyed by canonical symbol.

        Never raises: on failure it logs, records ``last_error`` and returns an
        empty mapping so the caller falls back to exchange data.
        """
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if self._cache and (now - self._cached_at) < self.ttl_seconds:
                return self._filtered(symbols)
            try:
                rows = await self._scan_all()
            except Exception as exc:
                self.last_error = str(exc)[:200]
                logger.warning(
                    "TradingView screener unavailable, using exchange data only",
                    extra={"error": self.last_error},
                )
                return {}
            self.last_error = None
            self._cache = rows
            self._cached_at = now
            return self._filtered(symbols)

    def _filtered(self, symbols: list[str] | None) -> dict[str, MarketStats]:
        if not symbols:
            return dict(self._cache)
        wanted = {s.upper() for s in symbols}
        return {key: value for key, value in self._cache.items() if key in wanted}

    # -- internals ----------------------------------------------------------
    async def _scan_all(self) -> dict[str, MarketStats]:
        """Page through the screener until every market of our exchange is read."""
        collected: dict[str, MarketStats] = {}
        offset = 0
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=_HEADERS) as client:
            while True:
                payload = {
                    "filter": [{"left": "exchange", "operation": "equal", "right": self.exchange}],
                    "columns": list(COLUMNS),
                    "sort": {"sortBy": "volume", "sortOrder": "desc"},
                    "range": [offset, offset + self.page_size],
                    "markets": ["crypto"],
                }
                response = await client.post(SCANNER_URL, json=payload)
                response.raise_for_status()
                body = response.json()
                data = body.get("data") or []
                if not data:
                    break
                for entry in data:
                    stats = self._parse_row(entry)
                    if stats is not None:
                        collected[stats.symbol] = stats
                total = int(body.get("totalCount") or 0)
                offset += self.page_size
                if offset >= total or offset >= 5000:
                    break
        logger.info("TradingView screener loaded", extra={"markets": len(collected)})
        return collected

    def _parse_row(self, entry: dict[str, Any]) -> MarketStats | None:
        tv_symbol = entry.get("s") or ""
        values = entry.get("d") or []
        if not tv_symbol or len(values) < len(COLUMNS):
            return None
        row = dict(zip(COLUMNS, values, strict=False))

        name = str(row.get("name") or "")
        want_perp = self.market_type == "futures"
        # Keep only the contract family we actually trade so a spot pair never
        # overwrites the perpetual row of the same coin.
        if want_perp != name.endswith(".P"):
            return None

        canonical = from_tradingview_symbol(f"{self.exchange}:{name}")
        rating = _num(row.get("Recommend.All"))
        return MarketStats(
            symbol=canonical,
            source=self.name,
            last_price=_num(row.get("close")),
            change_24h_pct=_num(row.get("change")),
            high_24h=_num(row.get("high")),
            low_24h=_num(row.get("low")),
            volume_24h=_num(row.get("volume")),
            extra={
                "tv_symbol": f"{self.exchange}:{name}",
                "tv_rating": rating,
                "tv_rating_label": rating_label(rating),
                "tv_rating_ma": _num(row.get("Recommend.MA")),
                "tv_rating_oscillators": _num(row.get("Recommend.Other")),
                "tv_rsi": _num(row.get("RSI")),
                "tv_atr": _num(row.get("ATR")),
                "tv_relative_volume": _num(row.get("relative_volume_10d_calc")),
                "tv_volatility_daily_pct": _num(row.get("Volatility.D")),
                "tv_average_volume_10d": _num(row.get("average_volume_10d_calc")),
            },
        )


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
