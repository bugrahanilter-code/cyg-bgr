"""A stop must be reachable before liquidation.

Leverage does not move a stop loss: a stop is a price. It moves the liquidation
price, toward the entry. Past a certain leverage the stop sits beyond
liquidation and can never fire, so instead of losing the amount that was meant
to be risked the account loses the entire margin.
"""

from __future__ import annotations

import pytest

from app.core.constants import SignalType
from app.exchange.filters import SymbolFilters, default_filters_for
from app.risk.config import RiskConfig
from app.risk.engine import RiskContext, RiskEngine
from app.risk.position_sizing import estimate_liquidation_price, max_safe_leverage
from app.signals.models import StrategySignal

ENTRY = 100.0


def signal_with_stop(stop_pct: float, side=SignalType.LONG) -> StrategySignal:
    direction = 1 if side == SignalType.LONG else -1
    return StrategySignal(
        symbol="BTC/USDT",
        timeframe="15m",
        strategy_key="trend_following",
        signal=side,
        candle_open_time=1_700_000_000_000,
        confidence=0.9,
        entry_price=ENTRY,
        stop_loss=ENTRY * (1 - direction * stop_pct / 100.0),
        take_profit=ENTRY * (1 + direction * stop_pct * 2 / 100.0),
        explanation="test",
    )


def context(leverage: float, filters=None) -> RiskContext:
    return RiskContext(
        equity=10_000.0,
        available_balance=10_000.0,
        daily_start_equity=10_000.0,
        leverage=leverage,
        filters=filters or default_filters_for("BTC/USDT"),
    )


class TestSafeLeverageMath:
    def test_a_wider_stop_allows_less_leverage(self) -> None:
        assert max_safe_leverage(1.0) > max_safe_leverage(5.0)

    def test_the_stop_sits_inside_liquidation_at_the_safe_leverage(self) -> None:
        for stop_pct in (0.5, 1.0, 2.5, 5.0, 8.0):
            leverage = max_safe_leverage(stop_pct)
            liquidation = estimate_liquidation_price(ENTRY, SignalType.LONG, leverage, 0.005)
            liquidation_pct = (ENTRY - liquidation) / ENTRY * 100.0
            assert liquidation_pct > stop_pct, (
                f"a {stop_pct}% stop at {leverage:.1f}x would be liquidated first"
            )

    def test_it_never_returns_less_than_one(self) -> None:
        assert max_safe_leverage(99.0) >= 1.0


class TestTheEngineCapsLeverage:
    def test_a_wide_stop_reduces_leverage(self) -> None:
        """The user's own configuration: 20x with a stop wider than the 4.5%
        liquidation distance. Before this guard the position was liquidated
        instead of stopped out."""
        engine = RiskEngine(RiskConfig(min_leverage=15, max_leverage=25))
        decision = engine.evaluate(signal_with_stop(6.0), context(20.0))
        assert decision.sizing is not None
        assert decision.sizing.leverage < 20.0
        assert any("before liquidation" in w for w in decision.warnings)

    def test_the_capped_leverage_keeps_the_stop_reachable(self) -> None:
        engine = RiskEngine(RiskConfig(min_leverage=1, max_leverage=25))
        decision = engine.evaluate(signal_with_stop(6.0), context(25.0))
        assert decision.sizing is not None
        liquidation = decision.sizing.liquidation_price
        assert liquidation is not None
        assert liquidation < decision.sizing.stop_loss, (
            "liquidation must sit further from entry than the stop"
        )

    def test_a_tight_stop_leaves_leverage_alone(self) -> None:
        """A 1% stop is safe at 20x, so nothing should be touched."""
        engine = RiskEngine(RiskConfig(min_leverage=1, max_leverage=25))
        decision = engine.evaluate(signal_with_stop(1.0), context(20.0))
        assert decision.sizing is not None
        assert decision.sizing.leverage == pytest.approx(20.0)

    def test_shorts_are_protected_too(self) -> None:
        engine = RiskEngine(RiskConfig(min_leverage=1, max_leverage=25))
        decision = engine.evaluate(signal_with_stop(6.0, SignalType.SHORT), context(20.0))
        assert decision.sizing is not None
        liquidation = decision.sizing.liquidation_price
        assert liquidation is not None
        assert liquidation > decision.sizing.stop_loss

    def test_risk_at_the_stop_is_unchanged_by_the_cap(self) -> None:
        """Lowering leverage must not change the position size or the money at
        risk - it only changes how much margin is posted."""
        engine = RiskEngine(RiskConfig(min_leverage=1, max_leverage=50))
        capped = engine.evaluate(signal_with_stop(6.0), context(40.0))
        modest = engine.evaluate(signal_with_stop(6.0), context(5.0))
        assert capped.sizing is not None and modest.sizing is not None
        assert capped.sizing.quantity == pytest.approx(modest.sizing.quantity, rel=1e-6)
        assert capped.sizing.risk_amount == pytest.approx(modest.sizing.risk_amount, rel=1e-6)

    def test_a_thin_market_cap_still_wins(self) -> None:
        thin = SymbolFilters(symbol="BTC/USDT", max_leverage=5)
        engine = RiskEngine(RiskConfig(min_leverage=20, max_leverage=25))
        decision = engine.evaluate(signal_with_stop(1.0), context(20.0, filters=thin))
        assert decision.sizing is not None
        assert decision.sizing.leverage <= 5.0
