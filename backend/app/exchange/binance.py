"""Binance connector built on top of ccxt.

Design notes
------------
* ccxt is synchronous, so every call is executed in a worker thread. This keeps
  the asyncio event loop responsive without adding a second HTTP stack.
* Market data works without API keys. Credentials are only required for
  account endpoints and for live order placement.
* Withdrawals are never called. The connector does not even implement them.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.constants import MarketType, OrderSide, OrderStatus, OrderType, PositionSide
from app.core.exceptions import ExchangeAuthError, ExchangeConnectionError, ExchangeError
from app.core.logging import get_logger
from app.core.security import register_sensitive_value
from app.core.time_utils import from_ms
from app.exchange.base import (
    AccountBalance,
    ExchangeGateway,
    ExchangeOrder,
    ExchangePosition,
    Ticker,
)
from app.exchange.filters import SymbolFilters, default_filters_for

logger = get_logger(__name__)

_STATUS_MAP = {
    "open": OrderStatus.NEW,
    "new": OrderStatus.NEW,
    "closed": OrderStatus.FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "expired": OrderStatus.EXPIRED,
    "rejected": OrderStatus.REJECTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
}


def _map_status(raw_status: str | None, filled: float, quantity: float) -> OrderStatus:
    """Translate a ccxt status into our own enum."""
    if raw_status:
        mapped = _STATUS_MAP.get(str(raw_status).lower())
        if mapped is not None:
            if mapped == OrderStatus.NEW and filled > 0 and filled < quantity:
                return OrderStatus.PARTIALLY_FILLED
            return mapped
    if quantity > 0 and filled >= quantity:
        return OrderStatus.FILLED
    if filled > 0:
        return OrderStatus.PARTIALLY_FILLED
    return OrderStatus.UNKNOWN


class BinanceGateway(ExchangeGateway):
    """Read/write gateway for Binance spot and USD-M futures."""

    name = "binance"
    supports_real_orders = True

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        market_type: MarketType = MarketType.FUTURES,
        testnet: bool = False,
        recv_window: int = 5000,
        request_timeout_ms: int = 20_000,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        register_sensitive_value(api_secret)
        register_sensitive_value(api_key)
        self.market_type = market_type
        self.testnet = testnet
        self.recv_window = recv_window
        self.request_timeout_ms = request_timeout_ms
        self._client: Any | None = None
        self._markets_loaded = False
        self._lock = asyncio.Lock()

    # -- construction -------------------------------------------------------
    @property
    def has_credentials(self) -> bool:
        return bool(self._api_key and self._api_secret)

    def _build_client(self) -> Any:
        import ccxt  # imported lazily so unit tests do not need the dependency

        config: dict[str, Any] = {
            "enableRateLimit": True,
            "timeout": self.request_timeout_ms,
            "options": {
                "adjustForTimeDifference": True,
                "recvWindow": self.recv_window,
                "defaultType": "future" if self.market_type == MarketType.FUTURES else "spot",
            },
        }
        if self.has_credentials:
            config["apiKey"] = self._api_key
            config["secret"] = self._api_secret

        exchange_class = (
            ccxt.binanceusdm if self.market_type == MarketType.FUTURES else ccxt.binance
        )
        client = exchange_class(config)
        if self.testnet:
            client.set_sandbox_mode(True)
        return client

    async def _get_client(self) -> Any:
        async with self._lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._build_client)
            return self._client

    async def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Run a ccxt method in a thread and normalise its exceptions."""
        import ccxt

        client = await self._get_client()
        method = getattr(client, method_name)
        try:
            return await asyncio.to_thread(method, *args, **kwargs)
        except ccxt.AuthenticationError as exc:
            raise ExchangeAuthError(f"Binance authentication failed: {exc}") from exc
        except ccxt.PermissionDenied as exc:
            raise ExchangeAuthError(f"Binance permission denied: {exc}") from exc
        except (ccxt.NetworkError, ccxt.RequestTimeout) as exc:
            raise ExchangeConnectionError(f"Binance connection problem: {exc}") from exc
        except ccxt.BaseError as exc:
            raise ExchangeError(f"Binance error in {method_name}: {exc}") from exc

    # -- symbol helpers -----------------------------------------------------
    async def _ensure_markets(self) -> dict[str, Any]:
        if not self._markets_loaded:
            await self._call("load_markets")
            self._markets_loaded = True
        client = await self._get_client()
        return client.markets or {}

    async def resolve_symbol(self, symbol: str) -> str:
        """Map a canonical symbol such as BTC/USDT to the ccxt market symbol."""
        markets = await self._ensure_markets()
        if symbol in markets:
            return symbol
        base_quote = symbol.split(":")[0]
        if base_quote in markets:
            return base_quote
        quote = base_quote.split("/")[-1]
        settled = f"{base_quote}:{quote}"
        if settled in markets:
            return settled
        raise ExchangeError(f"Symbol {symbol} is not available on Binance {self.market_type}")

    @staticmethod
    def to_canonical(market_symbol: str) -> str:
        """Strip the ccxt settlement suffix (BTC/USDT:USDT -> BTC/USDT)."""
        return market_symbol.split(":")[0]

    # -- lifecycle ----------------------------------------------------------
    async def connect(self) -> None:
        await self._ensure_markets()

    async def close(self) -> None:
        client = self._client
        self._client = None
        self._markets_loaded = False
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    await asyncio.to_thread(close)
                except Exception:  # pragma: no cover - best effort cleanup
                    logger.debug("Ignoring error while closing the Binance client")

    # -- market data --------------------------------------------------------
    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since_ms: int | None = None, limit: int = 500
    ) -> list[list[float]]:
        market = await self.resolve_symbol(symbol)
        rows = await self._call("fetch_ohlcv", market, timeframe, since_ms, limit)
        return [[float(value) for value in row[:6]] for row in rows or []]

    async def fetch_ticker(self, symbol: str) -> Ticker:
        market = await self.resolve_symbol(symbol)
        raw = await self._call("fetch_ticker", market)
        timestamp = raw.get("timestamp")
        return Ticker(
            symbol=self.to_canonical(symbol),
            last=float(raw.get("last") or raw.get("close") or 0.0),
            bid=float(raw["bid"]) if raw.get("bid") else None,
            ask=float(raw["ask"]) if raw.get("ask") else None,
            timestamp=from_ms(timestamp) if timestamp else None,
        )

    async def fetch_symbol_filters(self, symbol: str) -> SymbolFilters:
        markets = await self._ensure_markets()
        market_symbol = await self.resolve_symbol(symbol)
        market = markets.get(market_symbol) or {}
        limits = market.get("limits") or {}
        precision = market.get("precision") or {}
        fallback = default_filters_for(self.to_canonical(symbol))

        amount_step = precision.get("amount")
        price_step = precision.get("price")
        # ccxt reports precision either as decimal places or as a tick size.
        step_size = _precision_to_step(amount_step, fallback.step_size)
        tick_size = _precision_to_step(price_step, fallback.tick_size)

        min_amount = ((limits.get("amount") or {}).get("min")) or fallback.min_quantity
        min_cost = ((limits.get("cost") or {}).get("min")) or fallback.min_notional
        max_leverage = int(((limits.get("leverage") or {}).get("max")) or fallback.max_leverage)

        return SymbolFilters(
            symbol=self.to_canonical(symbol),
            tick_size=float(tick_size),
            step_size=float(step_size),
            min_quantity=float(min_amount),
            min_notional=float(min_cost),
            price_precision=_step_to_decimals(float(tick_size)),
            quantity_precision=_step_to_decimals(float(step_size)),
            max_leverage=max_leverage,
            maintenance_margin_rate=fallback.maintenance_margin_rate,
        )

    # -- account ------------------------------------------------------------
    async def fetch_balance(self) -> AccountBalance:
        if not self.has_credentials:
            raise ExchangeAuthError("Binance API credentials are required to read the balance")
        raw = await self._call("fetch_balance")
        quote = "USDT"
        info = raw.get("info") if isinstance(raw, dict) else None

        total = 0.0
        available = 0.0
        unrealized = 0.0
        if isinstance(info, dict):
            total = _as_float(info.get("totalWalletBalance"), 0.0)
            available = _as_float(info.get("availableBalance"), 0.0)
            unrealized = _as_float(info.get("totalUnrealizedProfit"), 0.0)
        if total <= 0:
            per_asset = raw.get(quote) if isinstance(raw, dict) else None
            if isinstance(per_asset, dict):
                total = _as_float(per_asset.get("total"), 0.0)
                available = _as_float(per_asset.get("free"), total)
        return AccountBalance(
            asset=quote, total=total, available=available, unrealized_pnl=unrealized
        )

    async def fetch_positions(self, symbols: list[str] | None = None) -> list[ExchangePosition]:
        if not self.has_credentials:
            raise ExchangeAuthError("Binance API credentials are required to read positions")
        if self.market_type != MarketType.FUTURES:
            return []
        markets = None
        if symbols:
            markets = [await self.resolve_symbol(symbol) for symbol in symbols]
        raw_positions = await self._call("fetch_positions", markets)

        positions: list[ExchangePosition] = []
        for raw in raw_positions or []:
            quantity = abs(_as_float(raw.get("contracts"), 0.0))
            if quantity <= 0:
                continue
            side_text = str(raw.get("side") or "").lower()
            side = PositionSide.LONG if side_text == "long" else PositionSide.SHORT
            positions.append(
                ExchangePosition(
                    symbol=self.to_canonical(str(raw.get("symbol"))),
                    side=side,
                    quantity=quantity,
                    entry_price=_as_float(raw.get("entryPrice"), 0.0),
                    mark_price=_as_float(raw.get("markPrice"), 0.0),
                    unrealized_pnl=_as_float(raw.get("unrealizedPnl"), 0.0),
                    leverage=_as_float(raw.get("leverage"), 1.0) or 1.0,
                    margin=_as_float(raw.get("initialMargin"), 0.0),
                    liquidation_price=_as_float(raw.get("liquidationPrice"), None),
                    raw=raw if isinstance(raw, dict) else {},
                )
            )
        return positions

    async def fetch_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        if not self.has_credentials:
            raise ExchangeAuthError("Binance API credentials are required to read orders")
        market = await self.resolve_symbol(symbol) if symbol else None
        raw_orders = await self._call("fetch_open_orders", market)
        return [self._parse_order(raw) for raw in raw_orders or []]

    async def fetch_order(self, symbol: str, client_order_id: str) -> ExchangeOrder | None:
        if not self.has_credentials:
            raise ExchangeAuthError("Binance API credentials are required to read orders")
        market = await self.resolve_symbol(symbol)
        try:
            raw = await self._call(
                "fetch_order", None, market, {"origClientOrderId": client_order_id}
            )
            if raw:
                return self._parse_order(raw)
        except ExchangeError:
            logger.debug("fetch_order by client id failed, scanning recent orders instead")
        try:
            recent = await self._call("fetch_orders", market, None, 50)
        except ExchangeError:
            return None
        for raw in recent or []:
            if raw.get("clientOrderId") == client_order_id:
                return self._parse_order(raw)
        return None

    # -- trading ------------------------------------------------------------
    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> ExchangeOrder:
        if not self.has_credentials:
            raise ExchangeAuthError("Binance API credentials are required to place orders")

        market = await self.resolve_symbol(symbol)
        params: dict[str, Any] = {}
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if reduce_only and self.market_type == MarketType.FUTURES:
            params["reduceOnly"] = True
        if stop_price is not None:
            params["stopPrice"] = stop_price

        ccxt_type = order_type.value
        if order_type == OrderType.LIMIT:
            params.setdefault("timeInForce", "GTC")
        if self.market_type == MarketType.SPOT:
            # Spot has no reduce-only flag and uses different conditional types.
            params.pop("reduceOnly", None)
            if order_type == OrderType.STOP_MARKET:
                ccxt_type = "STOP_LOSS"
            elif order_type == OrderType.TAKE_PROFIT_MARKET:
                ccxt_type = "TAKE_PROFIT"

        raw = await self._call(
            "create_order", market, ccxt_type, side.value.lower(), quantity, price, params
        )
        parsed = self._parse_order(raw)
        if parsed.client_order_id is None:
            parsed.client_order_id = client_order_id
        return parsed

    async def cancel_order(self, symbol: str, client_order_id: str) -> bool:
        market = await self.resolve_symbol(symbol)
        try:
            await self._call("cancel_order", None, market, {"origClientOrderId": client_order_id})
            return True
        except ExchangeError as exc:
            logger.warning("Could not cancel order", extra={"error": str(exc)})
            return False

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        if self.market_type != MarketType.FUTURES:
            return
        market = await self.resolve_symbol(symbol)
        try:
            await self._call("set_leverage", int(leverage), market)
        except ExchangeError as exc:
            # Binance rejects the call when the leverage is already correct.
            logger.info("set_leverage skipped", extra={"detail": str(exc)})

    # -- discovery ----------------------------------------------------------
    async def fetch_top_symbols_by_volume(
        self, limit: int = 10, quote: str = "USDT"
    ) -> list[dict[str, Any]]:
        """Return the highest 24h volume CRYPTO markets, one row per coin.

        Tokenised stocks and commodities (Binance lists them as EQUITY and
        COMMODITY) are filtered out: they follow stock-market hours and gap over
        weekends, which every strategy here would misread. Markets are also
        de-duplicated per base asset so BTC/USDT and BTC/USDC do not both appear
        and quietly double the exposure to one coin.
        """
        markets = await self._ensure_markets()
        tickers = await self._call("fetch_tickers")

        rows: list[dict[str, Any]] = []
        for market_symbol, ticker in (tickers or {}).items():
            market = markets.get(market_symbol) or {}
            info = market.get("info") or {}
            if self.market_type == MarketType.FUTURES:
                if info.get("underlyingType") != CRYPTO_UNDERLYING_TYPE:
                    continue
                if info.get("contractType") != PERPETUAL_CONTRACT_TYPE:
                    continue
                if info.get("status") not in (None, "TRADING"):
                    continue
            canonical = self.to_canonical(market_symbol)
            if not canonical.endswith(f"/{quote}"):
                continue
            volume = _as_float(ticker.get("quoteVolume"), 0.0) or 0.0
            if volume <= 0:
                continue
            rows.append(
                {
                    "symbol": canonical,
                    "base_asset": canonical.split("/")[0],
                    "quote_asset": quote,
                    "quote_volume_24h": volume,
                    "last_price": _as_float(ticker.get("last"), 0.0) or 0.0,
                    "change_24h_pct": _as_float(ticker.get("percentage"), 0.0) or 0.0,
                }
            )

        rows.sort(key=lambda row: row["quote_volume_24h"], reverse=True)
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if row["base_asset"] in seen:
                continue
            seen.add(row["base_asset"])
            unique.append(row)
            if len(unique) >= limit:
                break
        return unique

    async def fetch_market_universe(
        self,
        quote: str = "USDT",
        include_non_crypto: bool = False,
        always_include: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return EVERY tradable market on the exchange with its 24 hour stats.

        This is the unfiltered counterpart of :meth:`fetch_top_symbols_by_volume`.
        Instead of a top-N ranking it returns the whole universe so the dashboard
        can present it with its own search, sort and filter controls.

        Tokenised stocks and commodity indices are still flagged rather than
        silently dropped: ``is_crypto`` is False for them, so the UI can hide
        them by default while the user keeps the option of seeing them.
        """
        markets = await self._ensure_markets()
        tickers = await self._call("fetch_tickers")
        # The 24h ticker endpoint carries no order book, but the live spread is
        # the cost that decides whether a market is tradable at all, so it is
        # worth one extra call.
        try:
            books = await self._call("fetch_bids_asks")
        except ExchangeError as exc:
            logger.info("Order book snapshot unavailable", extra={"detail": str(exc)[:160]})
            books = {}

        rows: list[dict[str, Any]] = []
        for market_symbol, market in markets.items():
            info = market.get("info") or {}
            canonical = self.to_canonical(market_symbol)
            if quote and not canonical.endswith(f"/{quote}"):
                continue

            # A few named markets are wanted even though they fail the crypto
            # filter: XAU/USDT is a real, tradable Binance perpetual and is the
            # cost control the crypto studies are compared against.
            pinned = canonical in (always_include or set())

            if self.market_type == MarketType.FUTURES:
                status = info.get("status") or info.get("contractStatus")
                if status not in (None, "TRADING"):
                    continue
                contract = info.get("contractType")
                if contract != PERPETUAL_CONTRACT_TYPE and not pinned:
                    continue
                is_crypto = info.get("underlyingType") in (None, CRYPTO_UNDERLYING_TYPE)
            else:
                if market.get("active") is False:
                    continue
                is_crypto = True

            if not is_crypto and not include_non_crypto and not pinned:
                continue

            ticker = (tickers or {}).get(market_symbol) or {}
            book = (books or {}).get(market_symbol) or {}
            last = _as_float(ticker.get("last"), 0.0) or 0.0
            high = _as_float(ticker.get("high"), 0.0) or 0.0
            low = _as_float(ticker.get("low"), 0.0) or 0.0
            bid = _as_float(book.get("bid"), None) or _as_float(ticker.get("bid"), None)
            ask = _as_float(book.get("ask"), None) or _as_float(ticker.get("ask"), None)
            spread_pct = None
            if bid and ask and ask > 0:
                spread_pct = (ask - bid) / ((ask + bid) / 2.0) * 100.0

            rows.append(
                {
                    "symbol": canonical,
                    "base_asset": market.get("base") or canonical.split("/")[0],
                    "quote_asset": market.get("quote") or quote,
                    "is_crypto": bool(is_crypto),
                    "last_price": last,
                    "open_24h": _as_float(ticker.get("open"), 0.0) or 0.0,
                    "high_24h": high,
                    "low_24h": low,
                    "change_24h_pct": _as_float(ticker.get("percentage"), 0.0) or 0.0,
                    "change_24h_abs": _as_float(ticker.get("change"), 0.0) or 0.0,
                    "base_volume_24h": _as_float(ticker.get("baseVolume"), 0.0) or 0.0,
                    "quote_volume_24h": _as_float(ticker.get("quoteVolume"), 0.0) or 0.0,
                    "weighted_average": _as_float(ticker.get("vwap"), 0.0) or 0.0,
                    "trade_count_24h": int(_as_float(info.get("count"), 0.0) or 0.0),
                    "bid": bid,
                    "ask": ask,
                    "spread_pct": spread_pct,
                    # Where inside the 24h range the price currently sits (0-100).
                    "range_position_pct": (
                        (last - low) / (high - low) * 100.0 if high > low else None
                    ),
                    # Binance publishes leverage only through the (authenticated)
                    # bracket endpoint, so it is deliberately not guessed here.
                    "maint_margin_pct": _as_float(info.get("maintMarginPercent"), None),
                    "onboard_date": info.get("onboardDate"),
                }
            )

        rows.sort(key=lambda row: row["quote_volume_24h"], reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["volume_rank"] = rank
        return rows

    # -- diagnostics --------------------------------------------------------
    async def check_permissions(self) -> dict[str, Any]:
        """Best-effort inspection of the API key permissions.

        Used to warn the user when the withdrawal permission is still enabled.
        The endpoint only exists for spot keys, so a failure is reported as
        unknown rather than as an error.
        """
        result: dict[str, Any] = {"withdrawals_enabled": None, "checked": False}
        try:
            import ccxt

            spot = ccxt.binance(
                {
                    "apiKey": self._api_key,
                    "secret": self._api_secret,
                    "enableRateLimit": True,
                    "timeout": self.request_timeout_ms,
                }
            )
            if self.testnet:
                spot.set_sandbox_mode(True)
            raw = await asyncio.to_thread(spot.sapi_get_account_apirestrictions)
            result["checked"] = True
            result["withdrawals_enabled"] = bool(raw.get("enableWithdrawals"))
            result["ip_restricted"] = bool(raw.get("ipRestrict"))
            result["futures_enabled"] = bool(raw.get("enableFutures"))
        except Exception as exc:  # pragma: no cover - depends on the key type
            result["error"] = str(exc)[:200]
        return result

    # -- parsing ------------------------------------------------------------
    def _parse_order(self, raw: dict[str, Any]) -> ExchangeOrder:
        quantity = _as_float(raw.get("amount"), 0.0)
        filled = _as_float(raw.get("filled"), 0.0)
        fee_info = raw.get("fee") or {}
        side_text = str(raw.get("side") or "buy").upper()
        type_text = str(raw.get("type") or "market").upper().replace("-", "_")
        try:
            order_type = OrderType(type_text)
        except ValueError:
            order_type = OrderType.MARKET
        timestamp = raw.get("timestamp")
        fee_cost = fee_info.get("cost") if isinstance(fee_info, dict) else None
        return ExchangeOrder(
            symbol=self.to_canonical(str(raw.get("symbol") or "")),
            side=OrderSide.BUY if side_text == "BUY" else OrderSide.SELL,
            order_type=order_type,
            status=_map_status(raw.get("status"), filled, quantity),
            quantity=quantity,
            client_order_id=raw.get("clientOrderId"),
            exchange_order_id=str(raw.get("id")) if raw.get("id") is not None else None,
            price=_as_float(raw.get("price"), None),
            stop_price=_as_float(raw.get("stopPrice"), None),
            filled_quantity=filled,
            average_price=_as_float(raw.get("average"), None),
            fee=_as_float(fee_cost, 0.0) or 0.0,
            reduce_only=bool(raw.get("reduceOnly", False)),
            created_at=from_ms(timestamp) if timestamp else None,
            raw=raw if isinstance(raw, dict) else {},
        )


def _as_float(value: Any, default: float | None) -> Any:
    """Convert an exchange field to float, falling back to a default."""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _precision_to_step(precision: Any, fallback: float) -> float:
    """ccxt reports precision as decimal places or directly as a step size."""
    if precision is None:
        return fallback
    try:
        number = float(precision)
    except (TypeError, ValueError):
        return fallback
    if number <= 0:
        return fallback
    if number >= 1:
        return float(10 ** -int(number))
    return number


def _step_to_decimals(step: float) -> int:
    """Number of decimal places implied by a step or tick size."""
    if step <= 0:
        return 8
    text = f"{step:.12f}".rstrip("0")
    if "." not in text:
        return 0
    return len(text.split(".")[1])


#: Binance lists tokenised equities and commodities alongside crypto on its
#: futures venue. They trade on stock-market hours and gap over weekends, which
#: breaks every assumption a 24/7 crypto strategy makes, so they are excluded.
CRYPTO_UNDERLYING_TYPE = "COIN"
PERPETUAL_CONTRACT_TYPE = "PERPETUAL"
