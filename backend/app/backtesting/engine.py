"""Backtesting engine.

Execution model (deliberately pessimistic):

* a decision is taken on a CLOSED candle
* the fill happens at the OPEN of the next candle, with slippage
* stop loss and take profit are checked against the high/low of each candle
* if a candle could have hit both, the STOP is assumed to have hit first
* fees are charged on entry and exit, funding every 8 hours
* the daily loss limit and profit target stop new entries, exactly like live

This makes the results conservative. They are still not a promise: a backtest
describes the past, it does not predict the future.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.backtesting.costs import CostModel
from app.backtesting.metrics import (
    compute_metrics,
    drawdown_series,
    monthly_returns,
    trade_distribution,
)
from app.core.constants import DatasetSplit, ExitReason, SignalType, TradingMode
from app.core.exceptions import InsufficientDataError
from app.core.logging import get_logger
from app.core.time_utils import from_ms
from app.exchange.filters import SymbolFilters, default_filters_for
from app.regime.engine import MarketRegimeEngine, RegimeResult
from app.risk.config import RiskConfig
from app.risk.position_sizing import calculate_position_size
from app.strategies.base import BaseStrategy
from app.strategies.registry import create_strategy

logger = get_logger(__name__)

FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000


class BacktestRequest(BaseModel):
    """Everything needed to reproduce a backtest run."""

    strategy_key: str
    symbol: str
    timeframe: str = "15m"
    start: datetime
    end: datetime
    starting_capital: float = Field(default=10_000.0, gt=0.0)
    leverage: int = Field(default=2, ge=1, le=125)
    params: dict[str, Any] = Field(default_factory=dict)
    cost_model: CostModel = Field(default_factory=CostModel)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    split: DatasetSplit = DatasetSplit.FULL
    name: str = ""
    respect_daily_limits: bool = True


@dataclass(slots=True)
class BacktestOutput:
    """Result of one backtest run."""

    metrics: dict[str, Any] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    drawdown_curve: list[dict[str, Any]] = field(default_factory=list)
    monthly_returns: list[dict[str, Any]] = field(default_factory=list)
    trade_distribution: dict[str, Any] = field(default_factory=dict)
    candles_used: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _OpenTrade:
    """Internal representation of the single open position."""

    side: SignalType
    quantity: float
    entry_price: float
    intended_entry: float
    stop_loss: float
    take_profit: float | None
    margin: float
    leverage: float
    entry_fee: float
    entry_slippage: float
    opened_ms: int
    entry_index: int
    entry_reason: str
    confidence: float
    regime: str
    atr: float | None
    trailing_multiplier: float
    funding_paid: float = 0.0
    last_funding_bucket: int = 0
    extreme_price: float = 0.0
    trailing_stop: float | None = None

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity


class BacktestEngine:
    """Bar-by-bar simulator shared by the backtest lab and walk-forward runs."""

    def __init__(self, regime_engine: MarketRegimeEngine | None = None) -> None:
        self.regime_engine = regime_engine or MarketRegimeEngine()

    def run(
        self,
        frame: pd.DataFrame,
        request: BacktestRequest,
        filters: SymbolFilters | None = None,
        strategy: BaseStrategy | None = None,
    ) -> BacktestOutput:
        """Run the simulation over the given candle frame."""
        strategy = strategy or create_strategy(request.strategy_key, request.params)
        filters = filters or default_filters_for(request.symbol)
        output = BacktestOutput()

        if frame is None or frame.empty:
            raise InsufficientDataError("No candles available for this backtest")

        frame = frame.sort_values("open_time").reset_index(drop=True)
        warmup = max(strategy.warmup_bars, 220)
        if len(frame) <= warmup + 5:
            raise InsufficientDataError(
                f"Need more than {warmup + 5} candles for {request.strategy_key}, "
                f"received {len(frame)}. Choose a longer date range or a smaller timeframe."
            )

        prepared = strategy.prepare(frame, request.timeframe)
        annotated = self.regime_engine.annotate(frame)
        costs = request.cost_model
        risk = request.risk

        balance = float(request.starting_capital)
        peak_equity = balance
        position: _OpenTrade | None = None
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []

        current_day = None
        day_start_equity = balance
        daily_realized = 0.0
        trades_today = 0
        consecutive_losses = 0
        blocked_reason = ""

        last_index = len(frame) - 1

        for index in range(warmup, last_index):
            execution_index = index + request.cost_model.execution_delay_bars
            if execution_index > last_index:
                break

            execution_bar = frame.iloc[execution_index]
            bar_open = float(execution_bar["open"])
            bar_high = float(execution_bar["high"])
            bar_low = float(execution_bar["low"])
            bar_close = float(execution_bar["close"])
            bar_ms = int(execution_bar["open_time"])
            bar_day = from_ms(bar_ms).date()

            # --- new UTC day: reset the daily counters ---------------------
            if current_day != bar_day:
                current_day = bar_day
                unrealized = self._unrealized(position, bar_open)
                day_start_equity = balance + unrealized
                daily_realized = 0.0
                trades_today = 0
                blocked_reason = ""

            regime = self.regime_engine.result_at(annotated, index)
            position_side = position.side.value if position else None
            signal = strategy.evaluate(
                prepared,
                index,
                symbol=request.symbol,
                timeframe=request.timeframe,
                regime=regime,
                position_side=position_side,
            )

            # --- 1. signal driven exit executes at the next open -----------
            if position is not None and signal.signal in (SignalType.CLOSE, SignalType.HOLD):
                if signal.signal == SignalType.CLOSE:
                    fill = costs.fill_price(bar_open, position.side, is_entry=False)
                    trade, balance = self._close(
                        position, fill, bar_ms, ExitReason.SIGNAL_EXIT, costs, balance, request
                    )
                    trades.append(trade)
                    daily_realized += trade["net_pnl"]
                    consecutive_losses = 0 if trade["net_pnl"] > 0 else consecutive_losses + 1
                    position = None

            # --- 2. reversal: close the opposite position first ------------
            if position is not None and signal.is_entry and signal.signal != position.side:
                fill = costs.fill_price(bar_open, position.side, is_entry=False)
                trade, balance = self._close(
                    position, fill, bar_ms, ExitReason.SIGNAL_REVERSAL, costs, balance, request
                )
                trades.append(trade)
                daily_realized += trade["net_pnl"]
                consecutive_losses = 0 if trade["net_pnl"] > 0 else consecutive_losses + 1
                position = None

            # --- 3. entry ---------------------------------------------------
            if position is None and signal.is_entry:
                blocked_reason = self._entry_block_reason(
                    request=request,
                    daily_realized=daily_realized,
                    day_start_equity=day_start_equity,
                    trades_today=trades_today,
                    consecutive_losses=consecutive_losses,
                    equity=balance,
                    peak_equity=peak_equity,
                    signal_confidence=signal.confidence,
                    regime=regime,
                )
                if not blocked_reason and signal.entry_price and signal.stop_loss:
                    entry_fill = costs.fill_price(bar_open, signal.signal, is_entry=True)
                    stop_loss = self._shift_stop(signal, bar_open, entry_fill)
                    sizing = calculate_position_size(
                        equity=balance,
                        available_balance=balance,
                        entry_price=entry_fill,
                        stop_loss=stop_loss,
                        side=signal.signal,
                        filters=filters,
                        risk_per_trade_pct=risk.risk_per_trade_pct,
                        max_position_notional_pct=risk.max_position_notional_pct,
                        max_total_exposure_pct=risk.max_total_exposure_pct,
                        current_exposure=0.0,
                        leverage=min(request.leverage, risk.max_leverage),
                        margin_buffer_pct=risk.margin_buffer_pct,
                        taker_fee_pct=costs.taker_fee_pct,
                    )
                    if sizing.valid:
                        entry_fee = costs.fee_for(sizing.notional)
                        balance -= entry_fee
                        take_profit = self._shift_target(signal, bar_open, entry_fill)
                        position = _OpenTrade(
                            side=signal.signal,
                            quantity=sizing.quantity,
                            entry_price=entry_fill,
                            intended_entry=bar_open,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                            margin=sizing.margin,
                            leverage=sizing.leverage,
                            entry_fee=entry_fee,
                            entry_slippage=abs(entry_fill - bar_open) * sizing.quantity,
                            opened_ms=bar_ms,
                            entry_index=execution_index,
                            entry_reason=signal.explanation,
                            confidence=signal.confidence,
                            regime=regime.regime.value,
                            atr=signal.metadata.get("atr"),
                            trailing_multiplier=float(
                                signal.metadata.get("trailing_atr_multiplier", 0.0) or 0.0
                            ),
                            last_funding_bucket=bar_ms // FUNDING_INTERVAL_MS,
                            extreme_price=entry_fill,
                        )
                        trades_today += 1

            # --- 4. intrabar stop loss / take profit ------------------------
            if position is not None:
                exit_info = self._check_intrabar_exit(position, bar_high, bar_low)
                if exit_info is not None:
                    exit_price, reason = exit_info
                    fill = costs.fill_price(exit_price, position.side, is_entry=False)
                    trade, balance = self._close(
                        position, fill, bar_ms, reason, costs, balance, request
                    )
                    trades.append(trade)
                    daily_realized += trade["net_pnl"]
                    consecutive_losses = 0 if trade["net_pnl"] > 0 else consecutive_losses + 1
                    position = None

            # --- 5. funding and trailing stop -------------------------------
            if position is not None:
                if costs.apply_funding:
                    bucket = bar_ms // FUNDING_INTERVAL_MS
                    if bucket > position.last_funding_bucket:
                        intervals = int(bucket - position.last_funding_bucket)
                        direction = 1.0 if position.side == SignalType.LONG else -1.0
                        charge = (
                            position.quantity
                            * bar_close
                            * costs.funding_rate_pct_per_8h
                            / 100.0
                            * intervals
                            * direction
                        )
                        position.funding_paid += charge
                        position.last_funding_bucket = bucket
                self._update_trailing_stop(position, bar_high, bar_low, bar_close)

            # --- 6. equity bookkeeping --------------------------------------
            equity = balance + self._unrealized(position, bar_close)
            peak_equity = max(peak_equity, equity)
            equity_curve.append(
                {
                    "time": from_ms(bar_ms).isoformat(),
                    "timestamp_ms": bar_ms,
                    "equity": equity,
                    "balance": balance,
                    "in_position": position is not None,
                }
            )

        # --- close anything still open at the end of the test --------------
        if position is not None:
            final_bar = frame.iloc[last_index]
            fill = costs.fill_price(float(final_bar["close"]), position.side, is_entry=False)
            trade, balance = self._close(
                position,
                fill,
                int(final_bar["open_time"]),
                ExitReason.END_OF_BACKTEST,
                costs,
                balance,
                request,
            )
            trades.append(trade)
            equity_curve.append(
                {
                    "time": from_ms(int(final_bar["open_time"])).isoformat(),
                    "timestamp_ms": int(final_bar["open_time"]),
                    "equity": balance,
                    "balance": balance,
                    "in_position": False,
                }
            )

        duration_days = max(
            (int(frame["open_time"].iloc[-1]) - int(frame["open_time"].iloc[warmup]))
            / (1000 * 60 * 60 * 24),
            1e-9,
        )
        equity_values = [float(point["equity"]) for point in equity_curve]
        drawdown = drawdown_series(equity_values)

        output.trades = trades
        output.equity_curve = equity_curve
        output.drawdown_curve = [
            {"time": equity_curve[index]["time"], "drawdown_pct": value}
            for index, value in enumerate(drawdown.curve)
        ]
        output.metrics = compute_metrics(
            trades=trades,
            equity_curve=equity_curve,
            starting_capital=float(request.starting_capital),
            timeframe=request.timeframe,
            duration_days=duration_days,
        )
        output.metrics["split"] = request.split.value
        output.metrics["symbol"] = request.symbol
        output.metrics["strategy"] = request.strategy_key
        output.metrics["timeframe"] = request.timeframe
        output.monthly_returns = monthly_returns(equity_curve)
        output.trade_distribution = trade_distribution(trades)
        output.candles_used = int(len(frame))
        if not trades:
            output.warnings.append(
                "No trades were generated. The filters may be too strict for this period."
            )
        if len(trades) < 30:
            output.warnings.append(
                "Fewer than 30 trades: the statistics are not reliable. Treat them as noise."
            )
        return output

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _unrealized(position: _OpenTrade | None, price: float) -> float:
        if position is None:
            return 0.0
        direction = 1.0 if position.side == SignalType.LONG else -1.0
        return (price - position.entry_price) * position.quantity * direction

    @staticmethod
    def _shift_stop(signal, decision_price: float, fill_price: float) -> float:
        """Keep the stop the same distance away after slippage moved the entry."""
        if signal.entry_price is None or signal.stop_loss is None:
            return float(signal.stop_loss or 0.0)
        distance = signal.entry_price - signal.stop_loss
        return fill_price - distance

    @staticmethod
    def _shift_target(signal, decision_price: float, fill_price: float) -> float | None:
        if signal.entry_price is None or signal.take_profit is None:
            return None
        distance = signal.take_profit - signal.entry_price
        return fill_price + distance

    @staticmethod
    def _check_intrabar_exit(
        position: _OpenTrade, bar_high: float, bar_low: float
    ) -> tuple[float, ExitReason] | None:
        """Stop first: the pessimistic assumption when both levels are inside a bar."""
        stop = position.trailing_stop if position.trailing_stop is not None else position.stop_loss
        if position.side == SignalType.LONG:
            if stop is not None and bar_low <= stop:
                reason = (
                    ExitReason.TRAILING_STOP
                    if position.trailing_stop is not None
                    and position.trailing_stop > position.stop_loss
                    else ExitReason.STOP_LOSS
                )
                return stop, reason
            if position.take_profit is not None and bar_high >= position.take_profit:
                return position.take_profit, ExitReason.TAKE_PROFIT
            return None
        if stop is not None and bar_high >= stop:
            reason = (
                ExitReason.TRAILING_STOP
                if position.trailing_stop is not None
                and position.trailing_stop < position.stop_loss
                else ExitReason.STOP_LOSS
            )
            return stop, reason
        if position.take_profit is not None and bar_low <= position.take_profit:
            return position.take_profit, ExitReason.TAKE_PROFIT
        return None

    @staticmethod
    def _update_trailing_stop(
        position: _OpenTrade, bar_high: float, bar_low: float, bar_close: float
    ) -> None:
        if position.trailing_multiplier <= 0 or not position.atr:
            return
        distance = position.atr * position.trailing_multiplier
        if position.side == SignalType.LONG:
            position.extreme_price = max(position.extreme_price, bar_high)
            candidate = position.extreme_price - distance
            if position.trailing_stop is None or candidate > position.trailing_stop:
                position.trailing_stop = max(candidate, position.stop_loss)
        else:
            position.extreme_price = (
                min(position.extreme_price, bar_low) if position.extreme_price else bar_low
            )
            candidate = position.extreme_price + distance
            if position.trailing_stop is None or candidate < position.trailing_stop:
                position.trailing_stop = min(candidate, position.stop_loss)

    def _close(
        self,
        position: _OpenTrade,
        exit_price: float,
        exit_ms: int,
        reason: ExitReason,
        costs: CostModel,
        balance: float,
        request: BacktestRequest,
    ) -> tuple[dict[str, Any], float]:
        """Realise a position and return the trade record plus the new balance."""
        direction = 1.0 if position.side == SignalType.LONG else -1.0
        gross = (exit_price - position.entry_price) * position.quantity * direction
        exit_notional = exit_price * position.quantity
        exit_fee = costs.fee_for(exit_notional)
        fees = position.entry_fee + exit_fee
        funding = position.funding_paid
        net = gross - exit_fee - funding
        new_balance = balance + net
        duration = max(0, (exit_ms - position.opened_ms) // 1000)
        capital_base = position.margin or position.notional
        exit_slippage = abs(exit_notional) * costs.slippage_pct / 100.0
        slippage = position.entry_slippage + exit_slippage

        trade = {
            "symbol": request.symbol,
            "strategy": request.strategy_key,
            "timeframe": request.timeframe,
            "mode": TradingMode.BACKTEST.value,
            "side": position.side.value,
            "quantity": position.quantity,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "leverage": position.leverage,
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
            "notional": position.notional,
            "opened_at": from_ms(position.opened_ms).isoformat(),
            "closed_at": from_ms(exit_ms).isoformat(),
            "opened_ms": position.opened_ms,
            "closed_ms": exit_ms,
            "duration_seconds": int(duration),
            "gross_pnl": gross,
            "fees": fees,
            "funding": funding,
            "slippage_cost": slippage,
            "net_pnl": net,
            "return_pct": (net / capital_base * 100.0) if capital_base > 0 else 0.0,
            "equity_after": new_balance,
            "is_win": net > 0,
            "signal_confidence": position.confidence,
            "market_regime": position.regime,
            "entry_reason": position.entry_reason,
            "exit_reason": reason.value,
        }
        return trade, new_balance

    def _entry_block_reason(
        self,
        *,
        request: BacktestRequest,
        daily_realized: float,
        day_start_equity: float,
        trades_today: int,
        consecutive_losses: int,
        equity: float,
        peak_equity: float,
        signal_confidence: float,
        regime: RegimeResult,
    ) -> str:
        """Apply the same daily guards the live Risk Engine applies."""
        risk = request.risk
        if signal_confidence < risk.min_signal_confidence:
            return "confidence below the minimum"
        if risk.block_on_extreme_volatility and regime.is_extreme:
            return "extreme volatility"
        if not request.respect_daily_limits:
            return ""
        if day_start_equity > 0:
            daily_pct = daily_realized / day_start_equity * 100.0
            if daily_pct <= -abs(risk.daily_loss_limit_pct):
                return "daily loss limit reached"
            if daily_pct >= risk.daily_profit_target_pct:
                return "daily profit target reached"
        if trades_today >= risk.max_trades_per_day:
            return "maximum trades per day reached"
        if consecutive_losses >= risk.max_consecutive_losses:
            return "maximum consecutive losses reached"
        if peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity * 100.0
            if drawdown >= risk.max_drawdown_pct:
                return "maximum drawdown reached"
        return ""
