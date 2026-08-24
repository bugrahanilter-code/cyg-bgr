"""End to end paper trading and restart recovery tests."""

from __future__ import annotations

from app.core.constants import (
    BotStatus,
    EmergencyStopLevel,
    ExitReason,
    OrderSide,
    OrderType,
    PositionSide,
    SignalType,
    TradingMode,
)
from app.core.time_utils import utcnow
from app.exchange.base import AccountBalance, Ticker
from app.exchange.filters import default_filters_for
from app.exchange.simulated import SimulatedGateway
from app.execution.engine import ExecutionEngine
from app.portfolio.engine import PortfolioEngine
from app.risk.position_sizing import calculate_position_size
from app.services import bot_state_service
from app.signals.models import StrategySignal


def build_simulated(price: float = 30_000.0) -> SimulatedGateway:
    return SimulatedGateway(
        price_provider=lambda symbol: Ticker(
            symbol=symbol, last=price, bid=price * 0.9999, ask=price * 1.0001, timestamp=utcnow()
        ),
        balance_provider=lambda: AccountBalance(total=10_000.0, available=10_000.0),
        position_provider=list,
        taker_fee_pct=0.04,
        slippage_pct=0.02,
    )


async def test_simulated_gateway_applies_costs() -> None:
    gateway = build_simulated()
    order = await gateway.create_order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
    )
    assert order.status.value == "FILLED"
    assert order.average_price > 30_000.0  # slippage always hurts the buyer
    assert order.fee > 0


async def test_paper_round_trip_updates_balance_and_journal(db) -> None:
    portfolio = PortfolioEngine(TradingMode.PAPER)
    for position in portfolio.open_positions(db):
        position.status = "CLOSED"
    db.commit()

    starting_balance = portfolio.balance(db)
    gateway = build_simulated(30_000.0)
    execution = ExecutionEngine(
        gateway,
        mode=TradingMode.PAPER,
        portfolio=portfolio,
        filters_provider=default_filters_for,
        allow_real_orders=False,
        verify_attempts=1,
        verify_delay_seconds=0.0,
    )
    signal = StrategySignal(
        symbol="BTC/USDT",
        timeframe="15m",
        strategy_key="breakout_donchian",
        signal=SignalType.LONG,
        candle_open_time=1_700_000_999_000,
        confidence=0.7,
        entry_price=30_000.0,
        stop_loss=29_400.0,
        take_profit=31_200.0,
        explanation="paper test",
    )
    sizing = calculate_position_size(
        equity=starting_balance,
        available_balance=starting_balance,
        entry_price=30_000.0,
        stop_loss=29_400.0,
        side=SignalType.LONG,
        filters=default_filters_for("BTC/USDT"),
        risk_per_trade_pct=0.5,
        max_position_notional_pct=100.0,
        max_total_exposure_pct=200.0,
        current_exposure=0.0,
        leverage=2.0,
    )
    position = await execution.execute_entry(db, signal=signal, sizing=sizing, leverage=2.0)
    assert position is not None
    assert position.side == PositionSide.LONG.value

    profitable_gateway = build_simulated(31_500.0)
    execution.gateway = profitable_gateway
    trade = await execution.execute_exit(
        db, position, reason=ExitReason.TAKE_PROFIT, price_hint=31_500.0
    )
    assert trade is not None
    assert trade.net_pnl > 0
    assert trade.fees > 0
    assert trade.mode == TradingMode.PAPER.value
    assert portfolio.balance(db) > starting_balance

    stats = portfolio.daily_stats(db)
    assert stats.trades_count >= 1


def test_emergency_stop_survives_a_restart(db) -> None:
    """The kill switch is persisted, so a reboot cannot resume trading."""
    bot_state_service.set_emergency_stop(db, EmergencyStopLevel.FULL_STOP, "test")
    state = bot_state_service.get_state(db)
    assert state.emergency_stop_level == EmergencyStopLevel.FULL_STOP.value
    assert state.status == BotStatus.EMERGENCY_STOPPED.value

    db.expire_all()
    reloaded = bot_state_service.get_state(db)
    assert reloaded.emergency_stop_level == EmergencyStopLevel.FULL_STOP.value

    bot_state_service.set_emergency_stop(db, EmergencyStopLevel.NONE, "cleared")
    bot_state_service.set_status(db, BotStatus.STOPPED)


def test_live_trading_confirmation_is_persisted(db) -> None:
    bot_state_service.confirm_live_trading(db, True)
    assert bot_state_service.get_state(db).live_trading_confirmed is True
    bot_state_service.confirm_live_trading(db, False)
    assert bot_state_service.get_state(db).live_trading_confirmed is False
