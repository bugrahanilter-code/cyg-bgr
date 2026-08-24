"""Shared signal builders.

Every strategy expresses its risk the same way: a stop a number of ATR away
from the fill and a target expressed as a multiple of that risk. Centralising
the construction keeps the risk semantics identical across strategies, so the
Risk Engine and the backtester can treat them interchangeably.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.constants import SignalType
from app.indicators import safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal


def atr_entry_signal(
    *,
    strategy_key: str,
    symbol: str,
    timeframe: str,
    row: pd.Series,
    direction: SignalType,
    entry_price: float,
    atr_value: float,
    stop_multiplier: float,
    take_profit_r: float,
    confidence: float,
    explanation: str,
    indicators: dict[str, Any],
    regime: RegimeResult | None = None,
    trailing_multiplier: float = 0.0,
    stop_override: float | None = None,
    target_override: float | None = None,
) -> StrategySignal:
    """Build an entry signal with an ATR stop and an R-multiple target."""
    distance = abs(atr_value) * stop_multiplier
    if direction == SignalType.LONG:
        stop_loss = stop_override if stop_override is not None else entry_price - distance
        stop_loss = min(stop_loss, entry_price - 1e-9)
        risk = entry_price - stop_loss
        take_profit = (
            target_override if target_override is not None else entry_price + risk * take_profit_r
        )
    else:
        stop_loss = stop_override if stop_override is not None else entry_price + distance
        stop_loss = max(stop_loss, entry_price + 1e-9)
        risk = stop_loss - entry_price
        take_profit = (
            target_override if target_override is not None else entry_price - risk * take_profit_r
        )

    payload = dict(indicators)
    payload["atr"] = atr_value
    payload["stop_distance"] = abs(entry_price - stop_loss)

    return StrategySignal(
        symbol=symbol,
        timeframe=timeframe,
        strategy_key=strategy_key,
        signal=direction,
        candle_open_time=int(row["open_time"]),
        confidence=max(0.0, min(1.0, confidence)),
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        explanation=explanation,
        indicators=payload,
        regime=regime,
        metadata={"atr": atr_value, "trailing_atr_multiplier": trailing_multiplier},
    )


def close_signal(
    *,
    strategy_key: str,
    symbol: str,
    timeframe: str,
    row: pd.Series,
    reason: str,
    indicators: dict[str, Any],
    regime: RegimeResult | None = None,
    confidence: float = 0.6,
) -> StrategySignal:
    """Build an exit signal for an open position."""
    return StrategySignal(
        symbol=symbol,
        timeframe=timeframe,
        strategy_key=strategy_key,
        signal=SignalType.CLOSE,
        candle_open_time=int(row["open_time"]),
        confidence=confidence,
        entry_price=safe_float(row["close"]),
        explanation=reason,
        indicators=indicators,
        regime=regime,
    )
