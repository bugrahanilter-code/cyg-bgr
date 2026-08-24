"""The signal contract between strategies and the rest of the platform.

A signal is an *opinion*, never an order. Only the Risk Engine can turn it
into something the Execution Engine is allowed to act on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.constants import SignalType
from app.core.time_utils import from_ms, utcnow
from app.regime.engine import RegimeResult


@dataclass(slots=True)
class StrategySignal:
    """Everything a strategy has to say about one market at one point in time."""

    symbol: str
    timeframe: str
    strategy_key: str
    signal: SignalType
    candle_open_time: int
    confidence: float = 0.0
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    explanation: str = ""
    indicators: dict[str, Any] = field(default_factory=dict)
    regime: RegimeResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:24])

    # -- helpers ------------------------------------------------------------
    @property
    def is_actionable(self) -> bool:
        """True for LONG/SHORT/CLOSE, false for HOLD."""
        return self.signal in (SignalType.LONG, SignalType.SHORT, SignalType.CLOSE)

    @property
    def is_entry(self) -> bool:
        return self.signal in (SignalType.LONG, SignalType.SHORT)

    @property
    def candle_time(self) -> datetime:
        return from_ms(self.candle_open_time)

    @property
    def risk_distance(self) -> float | None:
        """Absolute distance between entry and stop loss."""
        if self.entry_price is None or self.stop_loss is None:
            return None
        return abs(self.entry_price - self.stop_loss)

    @property
    def risk_reward(self) -> float | None:
        """Reward/risk ratio implied by the stop loss and take profit."""
        distance = self.risk_distance
        if not distance or self.take_profit is None or self.entry_price is None:
            return None
        return abs(self.take_profit - self.entry_price) / distance

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy": self.strategy_key,
            "signal": self.signal.value,
            "confidence": round(self.confidence, 4),
            "candle_open_time": self.candle_open_time,
            "timestamp": self.created_at,
            "entry": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "explanation": self.explanation,
            "indicators": self.indicators,
            "regime": self.regime.to_dict() if self.regime else None,
            "metadata": self.metadata,
        }


def hold(
    symbol: str,
    timeframe: str,
    strategy_key: str,
    candle_open_time: int,
    explanation: str = "No setup",
    indicators: dict[str, Any] | None = None,
    regime: RegimeResult | None = None,
) -> StrategySignal:
    """Convenience constructor for the (very common) do-nothing decision."""
    return StrategySignal(
        symbol=symbol,
        timeframe=timeframe,
        strategy_key=strategy_key,
        signal=SignalType.HOLD,
        candle_open_time=candle_open_time,
        confidence=0.0,
        explanation=explanation,
        indicators=indicators or {},
        regime=regime,
    )
