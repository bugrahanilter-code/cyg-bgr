"""Market data service: candles, live prices and staleness tracking.

This is the only component that decides whether the platform currently has
trustworthy prices. If it says the data is stale, the Risk Engine refuses to
open new positions.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.core.constants import ConnectionStatus, HealthStatus, timeframe_to_ms
from app.core.logging import get_logger
from app.core.time_utils import seconds_since, to_ms, utcnow
from app.exchange.base import ExchangeGateway, Ticker
from app.market_data import reference_markets, store
from app.market_data.candles import OHLCV_COLUMNS, drop_unclosed_candle, rows_to_dataframe
from app.market_data.providers.yahoo import YahooHistoryProvider
from app.market_data.stream import BinanceWebSocketClient

logger = get_logger(__name__)

MAX_ROWS_PER_REQUEST = 1000


class MarketDataService:
    """Keeps candles and prices fresh for every enabled market."""

    def __init__(
        self,
        gateway: ExchangeGateway,
        *,
        symbols: list[str],
        timeframe: str,
        higher_timeframe: str = "4h",
        ws_base_url: str = "wss://fstream.binance.com/stream",
        stale_seconds: float = 120.0,
        poll_seconds: float = 15.0,
        enable_websocket: bool = True,
    ) -> None:
        self.gateway = gateway
        self.symbols = [symbol.upper() for symbol in symbols]
        self.timeframe = timeframe
        self.higher_timeframe = higher_timeframe
        self.stale_seconds = stale_seconds
        self.poll_seconds = poll_seconds
        self.enable_websocket = enable_websocket

        self._tickers: dict[str, Ticker] = {}
        self._ticker_updated_at: dict[str, datetime] = {}
        self._poll_task: asyncio.Task | None = None
        self._running = False
        self.rest_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self.last_rest_error: str = ""
        self.candle_listeners: list = []

        # Reference markets (EUR/USD, USD/JPY) have no Binance market at all, so
        # their candles come from a separate provider. Built on first use: most
        # installations never touch a non-Binance market.
        self._external_history: YahooHistoryProvider | None = None

        self._ws = BinanceWebSocketClient(
            symbols=self.symbols,
            timeframe=timeframe,
            base_url=ws_base_url,
            on_ticker=self._on_ticker,
            on_kline_closed=self._on_kline_closed,
        )

    # -- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self.enable_websocket:
            await self._ws.start()
        self._poll_task = asyncio.create_task(self._poll_loop(), name="market-data-poll")
        logger.info("Market data service started", extra={"symbols": self.symbols})

    async def stop(self) -> None:
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        await self._ws.stop()
        logger.info("Market data service stopped")

    # -- callbacks ----------------------------------------------------------
    def _on_ticker(self, ticker: Ticker) -> None:
        self._tickers[ticker.symbol] = ticker
        self._ticker_updated_at[ticker.symbol] = utcnow()

    def _on_kline_closed(self, symbol: str, timeframe: str, payload: dict) -> None:
        frame = rows_to_dataframe(
            [
                [
                    payload["open_time"],
                    payload["open"],
                    payload["high"],
                    payload["low"],
                    payload["close"],
                    payload["volume"],
                ]
            ]
        )
        try:
            from app.database.session import SessionLocal

            db = SessionLocal()
            try:
                store.save_candles(db, symbol, timeframe, frame)
            finally:
                db.close()
        except Exception as exc:  # pragma: no cover - persistence must not kill the stream
            logger.warning("Could not persist streamed candle", extra={"error": str(exc)})

        for listener in list(self.candle_listeners):
            try:
                listener(symbol, timeframe, payload)
            except Exception as exc:  # pragma: no cover - listener isolation
                logger.warning("Candle listener failed", extra={"error": str(exc)})

    # -- polling ------------------------------------------------------------
    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self.refresh_tickers()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Ticker polling failed", extra={"error": str(exc)})
            await asyncio.sleep(self.poll_seconds)

    async def refresh_tickers(self) -> None:
        """REST fallback that keeps prices alive when the websocket is down."""
        for symbol in self.symbols:
            if self._ws.status == ConnectionStatus.CONNECTED:
                age = seconds_since(self._ticker_updated_at.get(symbol))
                if age is not None and age < self.poll_seconds:
                    continue
            try:
                ticker = await self.gateway.fetch_ticker(symbol)
                self._on_ticker(ticker)
                self.rest_status = ConnectionStatus.CONNECTED
                self.last_rest_error = ""
            except Exception as exc:
                self.rest_status = ConnectionStatus.ERROR
                self.last_rest_error = str(exc)[:300]
                raise

    # -- price access -------------------------------------------------------
    def get_ticker(self, symbol: str) -> Ticker | None:
        """Latest cached ticker for a market."""
        return self._tickers.get(symbol.upper())

    def last_price(self, symbol: str) -> float | None:
        """Latest cached price, or None when unknown."""
        ticker = self.get_ticker(symbol)
        return ticker.last if ticker and ticker.last > 0 else None

    def data_age_seconds(self, symbol: str) -> float | None:
        """How old the newest price for a market is."""
        return seconds_since(self._ticker_updated_at.get(symbol.upper()))

    def is_stale(self, symbol: str | None = None) -> bool:
        """True when prices are too old to trade on."""
        symbols = [symbol.upper()] if symbol else self.symbols
        for item in symbols:
            age = self.data_age_seconds(item)
            if age is None or age > self.stale_seconds:
                return True
        return False

    def health(self) -> dict:
        """Health snapshot consumed by the monitoring endpoints."""
        ages = {symbol: self.data_age_seconds(symbol) for symbol in self.symbols}
        stale = self.is_stale()
        if self._ws.status == ConnectionStatus.CONNECTED and not stale:
            status = HealthStatus.OK
        elif not stale:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.DOWN
        return {
            "status": status.value,
            "websocket_status": self._ws.status.value,
            "websocket_last_message": self._ws.last_message_at,
            "websocket_reconnects": self._ws.reconnect_count,
            "websocket_error": self._ws.last_error,
            "rest_status": self.rest_status.value,
            "rest_error": self.last_rest_error,
            "stale": stale,
            "stale_threshold_seconds": self.stale_seconds,
            "data_age_seconds": ages,
            "prices": {
                symbol: (self._tickers[symbol].last if symbol in self._tickers else None)
                for symbol in self.symbols
            },
        }

    # -- historical data ----------------------------------------------------
    async def download_range(
        self,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
        db: Session | None = None,
        max_requests: int = 400,
    ) -> int:
        """Download and cache candles for a date range. Returns rows stored."""
        from app.database.session import SessionLocal

        owns_session = db is None
        session = db or SessionLocal()
        step = timeframe_to_ms(timeframe)
        session_gaps = reference_markets.has_session_gaps(symbol)
        cursor = start_ms
        stored = 0
        requests = 0
        try:
            # Skip what is already cached. Without this a matrix backtest
            # re-downloads a year of candles for every (market, timeframe) it
            # visits, even on a second run over the same grid.
            cached, first_cached, last_cached = store.range_coverage(
                session, symbol, timeframe, start_ms, end_ms
            )
            if cached:
                expected = max(1, (end_ms - start_ms) // step)
                covered_from_start = first_cached is not None and first_cached <= start_ms + step
                complete = cached >= expected * 0.98 and covered_from_start
                if complete and last_cached is not None and last_cached >= end_ms - 2 * step:
                    logger.debug(
                        "Candle range already cached",
                        extra={"symbol": symbol, "timeframe": timeframe, "candles": cached},
                    )
                    return 0
                if covered_from_start and last_cached is not None:
                    # Resume at the first missing candle rather than at the start.
                    cursor = max(cursor, last_cached + step)

            while cursor <= end_ms and requests < max_requests:
                rows = await self._fetch_ohlcv(symbol, timeframe, cursor)
                requests += 1
                if not rows:
                    break
                frame = rows_to_dataframe(rows)
                frame = frame[frame["open_time"] <= end_ms]
                if not frame.empty:
                    stored += store.save_candles(session, symbol, timeframe, frame)
                last_open = int(rows[-1][0])
                if last_open < cursor:
                    break
                cursor = last_open + step
                # A short page means "no more data" only on a market that never
                # closes. On FX a full week of calendar time contains roughly
                # five days of candles, so a short page is normal and the loop
                # has to keep walking until the window is covered.
                if len(rows) < MAX_ROWS_PER_REQUEST and not session_gaps:
                    break
        finally:
            if owns_session:
                session.close()
        logger.info(
            "Historical candles downloaded",
            extra={"symbol": symbol, "timeframe": timeframe, "stored": stored},
        )
        return stored

    def history_source(self, symbol: str) -> str:
        """Which provider serves this symbol's candles."""
        market = reference_markets.get(symbol)
        return market.provider if market else "binance"

    async def _fetch_ohlcv(
        self, symbol: str, timeframe: str, since_ms: int | None
    ) -> list[list[float]]:
        """Read raw candles from whichever source owns this symbol."""
        if self.history_source(symbol) == "yahoo":
            if getattr(self, "_external_history", None) is None:
                self._external_history = YahooHistoryProvider()
            return await self._external_history.fetch_ohlcv(
                symbol, timeframe, since_ms, MAX_ROWS_PER_REQUEST
            )
        return await self.gateway.fetch_ohlcv(symbol, timeframe, since_ms, MAX_ROWS_PER_REQUEST)

    async def sync_recent(
        self, symbol: str, timeframe: str, lookback: int = 500, db: Session | None = None
    ) -> int:
        """Top up the local cache with the most recent candles."""
        from app.database.session import SessionLocal

        owns_session = db is None
        session = db or SessionLocal()
        try:
            newest = store.latest_open_time(session, symbol, timeframe)
            step = timeframe_to_ms(timeframe)
            now_ms = to_ms(utcnow())
            start = now_ms - step * lookback if newest is None else newest + step
            if start > now_ms:
                return 0
            return await self.download_range(symbol, timeframe, start, now_ms, db=session)
        finally:
            if owns_session:
                session.close()

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        db: Session | None = None,
        closed_only: bool = True,
    ) -> pd.DataFrame:
        """Read cached candles. By default the forming candle is removed."""
        from app.database.session import SessionLocal

        owns_session = db is None
        session = db or SessionLocal()
        try:
            frame = store.load_candles(session, symbol, timeframe, limit=limit)
        finally:
            if owns_session:
                session.close()
        if frame.empty:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        if closed_only:
            frame = drop_unclosed_candle(frame, timeframe_to_ms(timeframe), to_ms(utcnow()))
        return frame

    async def get_candles_fresh(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        db: Session | None = None,
    ) -> pd.DataFrame:
        """Sync with the exchange first, then return closed candles."""
        try:
            await self.sync_recent(symbol, timeframe, lookback=limit, db=db)
        except Exception as exc:
            logger.warning(
                "Candle sync failed, serving cached data",
                extra={"symbol": symbol, "timeframe": timeframe, "error": str(exc)},
            )
        return self.get_candles(symbol, timeframe, limit=limit, db=db)

    def load_range(
        self,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
        db: Session | None = None,
    ) -> pd.DataFrame:
        """Read a cached date range (used by the backtester)."""
        from app.database.session import SessionLocal

        owns_session = db is None
        session = db or SessionLocal()
        try:
            return store.load_candles(session, symbol, timeframe, start_ms=start_ms, end_ms=end_ms)
        finally:
            if owns_session:
                session.close()
