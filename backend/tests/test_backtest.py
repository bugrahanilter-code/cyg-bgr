"""Backtest engine tests, including a hard look-ahead bias check."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from app.backtesting.costs import CostModel
from app.backtesting.engine import BacktestEngine, BacktestRequest
from app.backtesting.metrics import compute_metrics, drawdown_series, sharpe_ratio
from app.core.constants import SignalType
from app.core.exceptions import InsufficientDataError
from app.risk.config import RiskConfig


def build_request(**overrides) -> BacktestRequest:
    payload = {
        "strategy_key": "trend_following",
        "symbol": "BTC/USDT",
        "timeframe": "15m",
        "start": datetime(2024, 1, 1),
        "end": datetime(2024, 3, 1),
        "starting_capital": 10_000.0,
        "leverage": 2,
        "params": {"min_adx": 5.0, "momentum_threshold": 0.0},
        "cost_model": CostModel(taker_fee_pct=0.04, slippage_pct=0.02),
        "risk": RiskConfig(max_trades_per_day=50, max_consecutive_losses=20),
    }
    payload.update(overrides)
    return BacktestRequest(**payload)


def test_backtest_produces_metrics(trending_frame: pd.DataFrame) -> None:
    output = BacktestEngine().run(trending_frame, build_request())
    metrics = output.metrics
    for key in (
        "total_return_pct",
        "net_pnl",
        "final_balance",
        "total_trades",
        "win_rate_pct",
        "profit_factor",
        "expectancy",
        "max_drawdown_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "total_fees",
        "total_funding",
        "total_slippage",
    ):
        assert key in metrics
    assert len(output.equity_curve) > 0
    assert len(output.drawdown_curve) == len(output.equity_curve)


def test_costs_are_actually_charged(trending_frame: pd.DataFrame) -> None:
    output = BacktestEngine().run(trending_frame, build_request())
    if output.metrics["total_trades"] == 0:
        pytest.skip("This dataset produced no trades")
    assert output.metrics["total_fees"] > 0
    assert output.metrics["net_pnl"] < output.metrics["gross_pnl"] + 1e-9


def test_trades_are_chronological(trending_frame: pd.DataFrame) -> None:
    output = BacktestEngine().run(trending_frame, build_request())
    for trade in output.trades:
        assert trade["closed_ms"] >= trade["opened_ms"]
        assert trade["quantity"] > 0
        if trade["side"] == SignalType.LONG.value:
            assert trade["stop_loss"] < trade["entry_price"]


def test_no_lookahead_truncated_history_matches(trending_frame: pd.DataFrame) -> None:
    """Trades from a truncated dataset must match the full run exactly."""
    engine = BacktestEngine()
    request = build_request()
    truncated = trending_frame.iloc[:700].reset_index(drop=True)
    short_run = engine.run(truncated, request)
    full_run = engine.run(trending_frame, request)

    cutoff = int(truncated["open_time"].iloc[-1]) - 5 * 900_000
    early_short = [
        (trade["opened_ms"], trade["side"])
        for trade in short_run.trades
        if trade["closed_ms"] < cutoff and trade["exit_reason"] != "end_of_backtest"
    ]
    early_full = [
        (trade["opened_ms"], trade["side"])
        for trade in full_run.trades
        if trade["closed_ms"] < cutoff and trade["exit_reason"] != "end_of_backtest"
    ]
    assert early_short == early_full


def test_short_history_is_rejected() -> None:
    frame = pd.DataFrame(
        {
            "open_time": [1_700_000_000_000 + index * 900_000 for index in range(50)],
            "open": [100.0] * 50,
            "high": [101.0] * 50,
            "low": [99.0] * 50,
            "close": [100.0] * 50,
            "volume": [10.0] * 50,
        }
    )
    with pytest.raises(InsufficientDataError):
        BacktestEngine().run(frame, build_request())


def test_daily_loss_limit_stops_new_entries(volatile_frame: pd.DataFrame) -> None:
    strict = build_request(
        risk=RiskConfig(daily_loss_limit_pct=0.1, max_trades_per_day=100),
        params={"min_adx": 1.0, "momentum_threshold": 0.0},
    )
    relaxed = build_request(
        risk=RiskConfig(daily_loss_limit_pct=90.0, max_trades_per_day=100),
        params={"min_adx": 1.0, "momentum_threshold": 0.0},
    )
    engine = BacktestEngine()
    strict_output = engine.run(volatile_frame, strict)
    relaxed_output = engine.run(volatile_frame, relaxed)
    assert strict_output.metrics["total_trades"] <= relaxed_output.metrics["total_trades"]


def test_metric_helpers() -> None:
    curve = [100.0, 110.0, 90.0, 120.0]
    info = drawdown_series(curve)
    assert info.max_drawdown_pct == pytest.approx(18.1818, abs=0.01)
    assert sharpe_ratio(pd.Series([0.01, 0.02, -0.01]).to_numpy(), 365) != 0

    metrics = compute_metrics(
        trades=[{"net_pnl": 10.0, "return_pct": 1.0, "duration_seconds": 60}],
        equity_curve=[{"time": "2024-01-01", "equity": 100.0}, {"time": "2024-01-02", "equity": 110.0}],
        starting_capital=100.0,
        timeframe="15m",
        duration_days=1.0,
    )
    assert metrics["total_return_pct"] == pytest.approx(10.0)
    assert metrics["win_rate_pct"] == pytest.approx(100.0)
