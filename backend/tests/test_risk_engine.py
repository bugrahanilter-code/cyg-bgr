"""Risk Engine tests: the veto power must work in every scenario."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.constants import (
    EmergencyStopLevel,
    RiskRejectionCode,
    SignalType,
    TradingMode,
    VolatilityRegime,
)
from app.core.time_utils import utcnow
from app.exchange.filters import default_filters_for
from app.regime.engine import RegimeResult
from app.risk.config import RiskConfig
from app.risk.engine import OpenPositionInfo, RiskContext, RiskEngine
from app.signals.models import StrategySignal


def build_signal(**overrides) -> StrategySignal:
    payload = {
        "symbol": "BTC/USDT",
        "timeframe": "15m",
        "strategy_key": "trend_following",
        "signal": SignalType.LONG,
        "candle_open_time": 1_700_000_000_000,
        "confidence": 0.8,
        "entry_price": 30_000.0,
        "stop_loss": 29_400.0,
        "take_profit": 31_200.0,
        "explanation": "test",
    }
    payload.update(overrides)
    return StrategySignal(**payload)


def build_context(**overrides) -> RiskContext:
    payload = {
        "equity": 10_000.0,
        "available_balance": 10_000.0,
        "mode": TradingMode.PAPER,
        "daily_start_equity": 10_000.0,
        "leverage": 2.0,
        "filters": default_filters_for("BTC/USDT"),
    }
    payload.update(overrides)
    return RiskContext(**payload)


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine(RiskConfig())


def test_valid_signal_is_approved(engine: RiskEngine) -> None:
    decision = engine.evaluate(build_signal(), build_context())
    assert decision.approved, decision.summary
    assert decision.sizing is not None
    assert decision.sizing.quantity > 0


def test_emergency_stop_blocks_everything(engine: RiskEngine) -> None:
    context = build_context(emergency_stop=EmergencyStopLevel.HALT_NEW_ENTRIES)
    decision = engine.evaluate(build_signal(), context)
    assert not decision.approved
    assert RiskRejectionCode.EMERGENCY_STOP.value in decision.codes


def test_stale_market_data_blocks_entries(engine: RiskEngine) -> None:
    decision = engine.evaluate(build_signal(), build_context(market_data_stale=True))
    assert RiskRejectionCode.STALE_MARKET_DATA.value in decision.codes


def test_reconciliation_mismatch_blocks_entries(engine: RiskEngine) -> None:
    decision = engine.evaluate(build_signal(), build_context(reconciliation_ok=False))
    assert RiskRejectionCode.RECONCILIATION_MISMATCH.value in decision.codes


def test_daily_loss_limit_blocks_entries(engine: RiskEngine) -> None:
    context = build_context(daily_realized_pnl=-200.0)  # -2 percent of 10k
    decision = engine.evaluate(build_signal(), context)
    assert RiskRejectionCode.DAILY_LOSS_LIMIT_REACHED.value in decision.codes


def test_daily_profit_target_stops_new_trades(engine: RiskEngine) -> None:
    context = build_context(daily_realized_pnl=250.0)  # +2.5 percent
    decision = engine.evaluate(build_signal(), context)
    assert RiskRejectionCode.DAILY_PROFIT_TARGET_REACHED.value in decision.codes


def test_max_trades_per_day(engine: RiskEngine) -> None:
    decision = engine.evaluate(build_signal(), build_context(trades_today=15))
    assert RiskRejectionCode.MAX_TRADES_PER_DAY.value in decision.codes


def test_consecutive_losses_and_cooldown(engine: RiskEngine) -> None:
    context = build_context(consecutive_losses=3, last_loss_at=utcnow())
    decision = engine.evaluate(build_signal(), context)
    assert RiskRejectionCode.MAX_CONSECUTIVE_LOSSES.value in decision.codes
    assert RiskRejectionCode.COOLDOWN_ACTIVE.value in decision.codes


def test_cooldown_expires(engine: RiskEngine) -> None:
    context = build_context(
        consecutive_losses=1, last_loss_at=utcnow() - timedelta(minutes=45)
    )
    decision = engine.evaluate(build_signal(), context)
    assert RiskRejectionCode.COOLDOWN_ACTIVE.value not in decision.codes


def test_max_concurrent_positions(engine: RiskEngine) -> None:
    positions = [
        OpenPositionInfo(symbol="ETH/USDT", side=SignalType.LONG, notional=1000.0),
        OpenPositionInfo(symbol="SOL/USDT", side=SignalType.LONG, notional=1000.0),
    ]
    decision = engine.evaluate(build_signal(), build_context(open_positions=positions))
    assert RiskRejectionCode.MAX_CONCURRENT_POSITIONS.value in decision.codes


def test_one_position_per_symbol(engine: RiskEngine) -> None:
    positions = [OpenPositionInfo(symbol="BTC/USDT", side=SignalType.LONG, notional=500.0)]
    decision = engine.evaluate(build_signal(), build_context(open_positions=positions))
    assert RiskRejectionCode.POSITION_ALREADY_OPEN.value in decision.codes


def test_low_confidence_is_rejected(engine: RiskEngine) -> None:
    decision = engine.evaluate(build_signal(confidence=0.05), build_context())
    assert RiskRejectionCode.LOW_CONFIDENCE.value in decision.codes


def test_extreme_volatility_is_rejected(engine: RiskEngine) -> None:
    regime = RegimeResult(volatility=VolatilityRegime.EXTREME)
    decision = engine.evaluate(build_signal(), build_context(regime=regime))
    assert RiskRejectionCode.EXTREME_VOLATILITY.value in decision.codes


def test_wide_spread_is_rejected(engine: RiskEngine) -> None:
    decision = engine.evaluate(build_signal(), build_context(spread_pct=1.5))
    assert RiskRejectionCode.SPREAD_TOO_WIDE.value in decision.codes


def test_invalid_stop_loss_is_rejected(engine: RiskEngine) -> None:
    decision = engine.evaluate(build_signal(stop_loss=30_500.0), build_context())
    assert not decision.approved
    assert RiskRejectionCode.INVALID_STOP_LOSS.value in decision.codes


def test_live_mode_requires_confirmation(engine: RiskEngine) -> None:
    context = build_context(mode=TradingMode.LIVE, live_trading_confirmed=False)
    decision = engine.evaluate(build_signal(), context)
    assert RiskRejectionCode.LIVE_TRADING_NOT_ENABLED.value in decision.codes


def test_max_drawdown_blocks_trading(engine: RiskEngine) -> None:
    context = build_context(equity=8_000.0, peak_equity=10_000.0)
    decision = engine.evaluate(build_signal(), context)
    assert RiskRejectionCode.MAX_DRAWDOWN_REACHED.value in decision.codes


def test_hold_signal_is_never_executable(engine: RiskEngine) -> None:
    decision = engine.evaluate(build_signal(signal=SignalType.HOLD), build_context())
    assert not decision.approved
