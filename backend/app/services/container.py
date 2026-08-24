"""Application context.

Builds and owns the long-lived components (market data feed, exchange
gateways, trading engine) and rebuilds them when the configuration changes.

This is the composition root: it is the only place where the concrete
implementations are chosen.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import ConnectionStatus, HealthStatus, MarketType, TradingMode
from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.database.session import SessionLocal
from app.exchange.base import AccountBalance, ExchangeGateway, ExchangePosition
from app.exchange.binance import BinanceGateway
from app.exchange.filters import SymbolFilters, default_filters_for
from app.exchange.simulated import SimulatedGateway
from app.market_data.service import MarketDataService
from app.models.market import Symbol
from app.portfolio.engine import PortfolioEngine
from app.services import bot_state_service, credentials_service, settings_service
from app.services.rotation_scheduler import RotationScheduler
from app.services.trading_engine import TradingEngine

logger = get_logger(__name__)


class AppContext:
    """Singleton wiring for the running application."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.data_gateway: BinanceGateway | None = None
        self.rotation_scheduler = RotationScheduler(self)
        self.trading_gateway: ExchangeGateway | None = None
        self.market_data: MarketDataService | None = None
        self.engine: TradingEngine | None = None
        self.filters: dict[str, SymbolFilters] = {}
        self.exchange_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self.exchange_error: str = ""
        self.started = False
        self._lock = asyncio.Lock()

    # -- lifecycle ----------------------------------------------------------
    async def startup(self) -> None:
        """Build everything and start the background services."""
        async with self._lock:
            if self.started:
                return
            with SessionLocal() as db:
                await self._build(db)
            self.started = True

        if self.market_data is not None and self.settings.enable_background_engine:
            await self.market_data.start()

        with SessionLocal() as db:
            trading_config = settings_service.get_trading_config(db)
        if (
            self.engine is not None
            and trading_config.auto_start_engine
            and self.settings.enable_background_engine
        ):
            await self.engine.start()

        # The rotation clock runs whatever the engine is doing: it only edits
        # the enabled symbol list, and it checks its own on/off switch every
        # tick, so starting it here costs nothing when rotation is disabled.
        if self.settings.enable_background_engine:
            await self.rotation_scheduler.start()

    async def shutdown(self) -> None:
        """Stop background tasks and release network resources."""
        await self.rotation_scheduler.stop()
        if self.engine is not None:
            await self.engine.stop()
        if self.market_data is not None:
            await self.market_data.stop()
        for gateway in (self.trading_gateway, self.data_gateway):
            if gateway is not None:
                # Shutdown must never raise.
                with contextlib.suppress(Exception):
                    await gateway.close()
        self.started = False

    async def rebuild(self, db: Session) -> None:
        """Re-create the gateways and the engine after a settings change."""
        async with self._lock:
            was_running = self.engine is not None and self.engine.is_running
            if self.engine is not None:
                await self.engine.stop()
            if self.market_data is not None:
                await self.market_data.stop()
            await self._build(db)
        if self.market_data is not None and self.settings.enable_background_engine:
            await self.market_data.start()
        if was_running and self.engine is not None and self.settings.enable_background_engine:
            await self.engine.start()

    # -- construction -------------------------------------------------------
    async def _build(self, db: Session) -> None:
        """Choose the concrete implementations for the current configuration."""
        trading_config = settings_service.get_trading_config(db)
        credentials = credentials_service.resolve_credentials(db)
        state = bot_state_service.get_state(db)
        market_type = trading_config.market_type

        # Public gateway: market data works without any API key.
        self.data_gateway = BinanceGateway(
            api_key=credentials.api_key,
            api_secret=credentials.api_secret,
            market_type=market_type,
            testnet=credentials.testnet,
            recv_window=self.settings.binance_recv_window,
            request_timeout_ms=int(self.settings.request_timeout_seconds * 1000),
        )

        ws_base = (
            self.settings.binance_ws_base
            if market_type == MarketType.FUTURES
            else self.settings.binance_ws_base_spot
        )
        self.market_data = MarketDataService(
            self.data_gateway,
            symbols=trading_config.enabled_symbols,
            timeframe=trading_config.timeframe,
            higher_timeframe=trading_config.higher_timeframe,
            ws_base_url=ws_base,
            stale_seconds=self.settings.market_data_stale_seconds,
            poll_seconds=self.settings.market_data_poll_seconds,
            enable_websocket=self.settings.enable_background_engine,
        )

        self.filters = self._load_filters(db, trading_config.enabled_symbols)

        mode = trading_config.mode
        allow_real_orders = (
            mode == TradingMode.LIVE
            and self.settings.live_trading_enabled
            and bool(state.live_trading_confirmed)
            and credentials.is_present
        )

        if mode == TradingMode.LIVE and allow_real_orders:
            self.trading_gateway = self.data_gateway
            logger.warning("LIVE TRADING IS ACTIVE: real orders can be sent to Binance")
        else:
            if mode == TradingMode.LIVE:
                logger.warning(
                    "Live mode requested but not fully authorised. Falling back to simulation."
                )
                mode = TradingMode.PAPER
            self.trading_gateway = self._build_simulated_gateway(market_type)

        self.engine = TradingEngine(
            market_data=self.market_data,
            gateway=self.trading_gateway,
            mode=mode,
            loop_interval=self.settings.engine_loop_interval_seconds,
            reconciliation_interval=self.settings.reconciliation_interval_seconds,
            allow_real_orders=allow_real_orders,
            filters=self.filters,
        )
        logger.info(
            "Application context built",
            extra={
                "mode": mode.value,
                "symbols": trading_config.enabled_symbols,
                "gateway": self.trading_gateway.name,
                "allow_real_orders": allow_real_orders,
            },
        )

    def _build_simulated_gateway(self, market_type: MarketType) -> SimulatedGateway:
        """Paper trading gateway backed by real prices and local balances."""
        portfolio = PortfolioEngine(TradingMode.PAPER)

        def price_provider(symbol: str):
            return self.market_data.get_ticker(symbol) if self.market_data else None

        def balance_provider() -> AccountBalance:
            with SessionLocal() as db:
                state = portfolio.account_state(db)
            return AccountBalance(
                asset="USDT",
                total=state.balance,
                available=state.available,
                unrealized_pnl=state.unrealized_pnl,
            )

        def position_provider() -> list[ExchangePosition]:
            from app.core.constants import PositionSide

            with SessionLocal() as db:
                positions = portfolio.open_positions(db)
                return [
                    ExchangePosition(
                        symbol=position.symbol,
                        side=PositionSide(position.side),
                        quantity=float(position.quantity),
                        entry_price=float(position.entry_price),
                        mark_price=float(position.entry_price),
                        unrealized_pnl=float(position.unrealized_pnl or 0.0),
                        leverage=float(position.leverage or 1.0),
                        margin=float(position.margin or 0.0),
                    )
                    for position in positions
                ]

        return SimulatedGateway(
            price_provider=price_provider,
            balance_provider=balance_provider,
            position_provider=position_provider,
            filters_provider=lambda symbol: self.filters.get(
                symbol.upper(), default_filters_for(symbol)
            ),
            data_gateway=self.data_gateway,
            taker_fee_pct=self.settings.taker_fee_pct,
            slippage_pct=self.settings.slippage_pct,
            market_type=market_type,
        )

    @staticmethod
    def _load_filters(db: Session, symbols: list[str]) -> dict[str, SymbolFilters]:
        """Read the exchange filters cached in the symbols table."""
        result: dict[str, SymbolFilters] = {}
        for symbol in symbols:
            row = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).one_or_none()
            if row is None:
                result[symbol.upper()] = default_filters_for(symbol)
                continue
            result[symbol.upper()] = SymbolFilters(
                symbol=row.symbol,
                tick_size=float(row.tick_size),
                step_size=float(row.step_size),
                min_quantity=float(row.min_quantity),
                min_notional=float(row.min_notional),
                price_precision=int(row.price_precision),
                quantity_precision=int(row.quantity_precision),
                max_leverage=int(row.max_leverage),
                maintenance_margin_rate=float(row.maintenance_margin_rate),
            )
        return result

    # -- exchange operations -----------------------------------------------
    async def refresh_symbol_filters(self, db: Session) -> dict[str, Any]:
        """Download the real trading rules and cache them in the database."""
        if self.data_gateway is None:
            return {"updated": 0}
        updated = 0
        trading_config = settings_service.get_trading_config(db)
        for symbol in trading_config.enabled_symbols:
            try:
                filters = await self.data_gateway.fetch_symbol_filters(symbol)
            except Exception as exc:
                logger.warning(
                    "Could not refresh filters", extra={"symbol": symbol, "error": str(exc)}
                )
                continue
            row = db.query(Symbol).filter(Symbol.symbol == symbol.upper()).one_or_none()
            if row is None:
                continue
            row.tick_size = filters.tick_size
            row.step_size = filters.step_size
            row.min_quantity = filters.min_quantity
            row.min_notional = filters.min_notional
            row.price_precision = filters.price_precision
            row.quantity_precision = filters.quantity_precision
            row.max_leverage = filters.max_leverage

            row.filters_synced_at = utcnow()
            self.filters[symbol.upper()] = filters
            updated += 1
        db.commit()
        if self.engine is not None:
            self.engine.filters = self.filters
        return {"updated": updated}

    async def discover_top_symbols(self, limit: int = 10) -> list[dict[str, Any]]:
        """List the highest volume crypto markets on the exchange."""
        if self.data_gateway is None:
            return []
        return await self.data_gateway.fetch_top_symbols_by_volume(
            limit=limit, quote=self.settings.quote_currency
        )

    async def sync_top_symbols(self, db: Session, limit: int = 10) -> dict[str, Any]:
        """Add the highest volume crypto markets to the symbols table.

        The markets become *available*; they are not switched on for trading.
        Enabling a market is a deliberate decision the user makes in Settings,
        because every extra market multiplies the number of strategy
        evaluations and the number of positions that can be opened.
        """
        discovered = await self.discover_top_symbols(limit)
        added: list[str] = []
        updated: list[str] = []

        for entry in discovered:
            symbol = entry["symbol"]
            row = db.query(Symbol).filter(Symbol.symbol == symbol).one_or_none()
            try:
                filters = await self.data_gateway.fetch_symbol_filters(symbol)  # type: ignore[union-attr]
            except Exception as exc:
                logger.warning(
                    "Could not read filters for a discovered market",
                    extra={"symbol": symbol, "error": str(exc)},
                )
                filters = default_filters_for(symbol)

            if row is None:
                row = Symbol(
                    symbol=symbol,
                    base_asset=entry["base_asset"],
                    quote_asset=entry["quote_asset"],
                    market_type=self.settings.binance_market_type.value,
                    enabled=False,
                )
                db.add(row)
                added.append(symbol)
            else:
                updated.append(symbol)

            row.tick_size = filters.tick_size
            row.step_size = filters.step_size
            row.min_quantity = filters.min_quantity
            row.min_notional = filters.min_notional
            row.price_precision = filters.price_precision
            row.quantity_precision = filters.quantity_precision
            row.max_leverage = filters.max_leverage
            row.filters_synced_at = utcnow()
            self.filters[symbol] = filters

        db.commit()
        if self.engine is not None:
            self.engine.filters = self.filters
        logger.info(
            "Top volume markets synchronised",
            extra={"added": len(added), "updated": len(updated)},
        )
        return {"discovered": discovered, "added": added, "updated": updated}

    async def test_exchange_connection(self, db: Session) -> dict[str, Any]:
        """Verify credentials, report permissions and warn about withdrawals."""
        credentials = credentials_service.resolve_credentials(db)
        result: dict[str, Any] = {
            "connected": False,
            "authenticated": False,
            "market_data_ok": False,
            "message": "",
            "permissions": {},
            "source": credentials.source,
        }
        gateway = BinanceGateway(
            api_key=credentials.api_key,
            api_secret=credentials.api_secret,
            market_type=credentials.market_type,
            testnet=credentials.testnet,
            recv_window=self.settings.binance_recv_window,
        )
        try:
            ticker = await gateway.fetch_ticker("BTC/USDT")
            result["market_data_ok"] = ticker.last > 0
            result["connected"] = True
            self.exchange_status = ConnectionStatus.CONNECTED
            self.exchange_error = ""
        except Exception as exc:
            self.exchange_status = ConnectionStatus.ERROR
            self.exchange_error = str(exc)[:300]
            result["message"] = f"Market data unreachable: {exc}"
            await gateway.close()
            return result

        if not credentials.is_present:
            result["message"] = (
                "Public market data works. Add an API key to read your balance and to trade."
            )
            await gateway.close()
            return result

        try:
            balance = await gateway.fetch_balance()
            result["authenticated"] = True
            result["balance"] = balance.total
            result["message"] = "Connected to Binance and authenticated."
        except Exception as exc:
            result["message"] = f"Credentials rejected: {exc}"
            credentials_service.record_test_result(db, ok=False, message=result["message"])
            await gateway.close()
            return result

        permissions = await gateway.check_permissions()
        result["permissions"] = permissions
        if permissions.get("withdrawals_enabled") is True:
            result["message"] += (
                " WARNING: this API key has the withdrawal permission enabled. "
                "Disable it on Binance immediately."
            )
        credentials_service.record_test_result(
            db, ok=True, message=result["message"], permissions=permissions
        )
        await gateway.close()
        return result

    # -- health -------------------------------------------------------------
    def health(self, db: Session) -> dict[str, Any]:
        """Component-by-component health used by the monitoring page."""
        state = bot_state_service.get_state(db)
        market_health = (
            self.market_data.health()
            if self.market_data is not None
            else {"status": HealthStatus.DOWN.value}
        )
        engine_status = self.engine.status() if self.engine is not None else {"running": False}
        database_ok = True
        try:
            db.execute(text("SELECT 1"))
        except Exception:  # pragma: no cover - database down
            database_ok = False

        # Receiving Binance data is itself proof that the exchange is
        # reachable, so an untested connection is not reported as down.
        exchange_status = self.exchange_status
        if exchange_status != ConnectionStatus.CONNECTED:
            reachable = ConnectionStatus.CONNECTED.value in (
                market_health.get("websocket_status"),
                market_health.get("rest_status"),
            )
            if reachable:
                exchange_status = ConnectionStatus.CONNECTED

        return {
            "market_data": market_health,
            "engine": engine_status,
            "database": {
                "status": HealthStatus.OK.value if database_ok else HealthStatus.DOWN.value,
                "dialect": db.bind.dialect.name if db.bind is not None else "unknown",
            },
            "exchange": {
                "status": exchange_status.value,
                "error": self.exchange_error,
                "gateway": self.trading_gateway.name if self.trading_gateway else "none",
                "supports_real_orders": bool(
                    self.trading_gateway and self.trading_gateway.supports_real_orders
                ),
            },
            "reconciliation": {
                "status": state.reconciliation_status,
                "last_run": state.last_reconciliation_at,
                "details": state.reconciliation_details,
            },
            "bot_state": {
                "status": state.status,
                "mode": state.mode,
                "emergency_stop_level": state.emergency_stop_level,
                "live_trading_confirmed": bool(state.live_trading_confirmed),
                "last_heartbeat": state.last_heartbeat,
                "halt_reason": state.halt_reason,
            },
        }


#: Module level singleton used by the API layer.
context = AppContext()
