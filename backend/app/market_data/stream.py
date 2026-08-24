"""Binance public WebSocket client.

Features required for safe trading:

* automatic reconnect with exponential backoff
* heartbeat / idle detection (a silent socket is treated as broken)
* every message updates a timestamp so the rest of the system can decide
  whether the market data is stale
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Iterable
from datetime import datetime

from app.core.constants import ConnectionStatus
from app.core.logging import get_logger
from app.core.time_utils import from_ms, utcnow
from app.exchange.base import Ticker

logger = get_logger(__name__)

TickerCallback = Callable[[Ticker], None]
KlineCallback = Callable[[str, str, dict], None]


def to_stream_symbol(symbol: str) -> str:
    """BTC/USDT -> btcusdt."""
    return symbol.replace("/", "").split(":")[0].lower()


class BinanceWebSocketClient:
    """Subscribes to book ticker and kline streams for the enabled markets."""

    def __init__(
        self,
        *,
        symbols: Iterable[str],
        timeframe: str,
        base_url: str,
        on_ticker: TickerCallback | None = None,
        on_kline_closed: KlineCallback | None = None,
        idle_timeout: float = 45.0,
    ) -> None:
        self.symbols = [symbol.upper() for symbol in symbols]
        self.timeframe = timeframe
        self.base_url = base_url.rstrip("/")
        self.on_ticker = on_ticker
        self.on_kline_closed = on_kline_closed
        self.idle_timeout = idle_timeout

        self.status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self.last_message_at: datetime | None = None
        self.last_error: str = ""
        self.reconnect_count = 0
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # -- lifecycle ----------------------------------------------------------
    def build_url(self) -> str:
        streams: list[str] = []
        for symbol in self.symbols:
            stream_symbol = to_stream_symbol(symbol)
            streams.append(f"{stream_symbol}@bookTicker")
            streams.append(f"{stream_symbol}@kline_{self.timeframe}")
        return f"{self.base_url}?streams=" + "/".join(streams)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="binance-ws")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.status = ConnectionStatus.DISCONNECTED

    # -- main loop ----------------------------------------------------------
    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping.is_set():
            self.status = ConnectionStatus.CONNECTING
            try:
                import websockets

                url = self.build_url()
                logger.info("Connecting to Binance websocket", extra={"streams": len(self.symbols)})
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=20, close_timeout=5, max_queue=256
                ) as socket:
                    self.status = ConnectionStatus.CONNECTED
                    self.last_error = ""
                    backoff = 1.0
                    await self._consume(socket)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status = ConnectionStatus.ERROR
                self.last_error = str(exc)[:300]
                self.reconnect_count += 1
                logger.warning(
                    "Websocket disconnected, reconnecting",
                    extra={"error": self.last_error, "backoff_seconds": backoff},
                )
            if self._stopping.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)
        self.status = ConnectionStatus.DISCONNECTED

    async def _consume(self, socket) -> None:
        while not self._stopping.is_set():
            try:
                raw = await asyncio.wait_for(socket.recv(), timeout=self.idle_timeout)
            except TimeoutError as exc:
                raise ConnectionError("No websocket message received within the idle timeout") from exc
            self.last_message_at = utcnow()
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            self._dispatch(payload)

    def _dispatch(self, payload: dict) -> None:
        data = payload.get("data") if isinstance(payload, dict) else None
        stream = payload.get("stream", "") if isinstance(payload, dict) else ""
        if not isinstance(data, dict):
            return
        if "@bookTicker" in stream or data.get("e") == "bookTicker":
            self._handle_book_ticker(data)
        elif data.get("e") == "kline":
            self._handle_kline(data)

    def _handle_book_ticker(self, data: dict) -> None:
        if self.on_ticker is None:
            return
        raw_symbol = str(data.get("s") or "")
        symbol = self._canonical(raw_symbol)
        try:
            bid = float(data.get("b"))
            ask = float(data.get("a"))
        except (TypeError, ValueError):
            return
        self.on_ticker(
            Ticker(symbol=symbol, last=(bid + ask) / 2.0, bid=bid, ask=ask, timestamp=utcnow())
        )

    def _handle_kline(self, data: dict) -> None:
        candle = data.get("k") or {}
        if not candle.get("x"):  # only closed candles matter for decisions
            return
        if self.on_kline_closed is None:
            return
        symbol = self._canonical(str(data.get("s") or ""))
        payload = {
            "open_time": int(candle.get("t", 0)),
            "close_time": int(candle.get("T", 0)),
            "open": float(candle.get("o", 0.0)),
            "high": float(candle.get("h", 0.0)),
            "low": float(candle.get("l", 0.0)),
            "close": float(candle.get("c", 0.0)),
            "volume": float(candle.get("v", 0.0)),
            "closed_at": from_ms(int(candle.get("T", 0))) if candle.get("T") else utcnow(),
        }
        self.on_kline_closed(symbol, str(candle.get("i") or self.timeframe), payload)

    def _canonical(self, raw_symbol: str) -> str:
        """BTCUSDT -> BTC/USDT (using the configured symbol list)."""
        upper = raw_symbol.upper()
        for symbol in self.symbols:
            if symbol.replace("/", "") == upper:
                return symbol
        if upper.endswith("USDT"):
            return f"{upper[:-4]}/USDT"
        return upper
