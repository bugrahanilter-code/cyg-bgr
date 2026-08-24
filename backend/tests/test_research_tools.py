"""Tests for the research tooling: Monte Carlo, portfolio simulation, stability."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.monte_carlo import run_monte_carlo
from app.backtesting.portfolio_sim import simulate_portfolio
from app.backtesting.research import buy_and_hold


def test_monte_carlo_refuses_a_tiny_sample() -> None:
    result = run_monte_carlo([10.0, -5.0], starting_capital=1000.0)
    assert result["ran"] is False
    assert "meaningless" in result["reason"]


def test_monte_carlo_reports_a_distribution() -> None:
    rng = np.random.default_rng(7)
    trades = list(rng.normal(5.0, 40.0, 200))
    result = run_monte_carlo(trades, starting_capital=10_000.0, simulations=2_000)

    assert result["ran"] is True
    assert result["trades"] == 200
    assert result["return_p5_pct"] <= result["median_return_pct"] <= result["return_p95_pct"]
    assert result["median_max_drawdown_pct"] <= result["worst_drawdown_pct"]
    assert 0.0 <= result["probability_of_profit_pct"] <= 100.0


def test_monte_carlo_is_reproducible() -> None:
    trades = [12.0, -8.0, 30.0, -15.0, 4.0, -2.0, 18.0, -9.0, 6.0, -3.0]
    first = run_monte_carlo(trades, 1000.0, simulations=500, seed=99)
    second = run_monte_carlo(trades, 1000.0, simulations=500, seed=99)
    assert first["median_return_pct"] == second["median_return_pct"]


def _trade(symbol: str, opened: int, closed: int, pnl: float) -> dict:
    return {"symbol": symbol, "opened_ms": opened, "closed_ms": closed, "net_pnl": pnl}


def test_portfolio_caps_concurrent_positions() -> None:
    """Four overlapping signals, three allowed: one must be refused."""
    trades = {
        "BTC/USDT": [_trade("BTC/USDT", 0, 100, 10.0)],
        "ETH/USDT": [_trade("ETH/USDT", 1, 100, 10.0)],
        "XRP/USDT": [_trade("XRP/USDT", 2, 100, 10.0)],
        "DOGE/USDT": [_trade("DOGE/USDT", 3, 100, 10.0)],
    }
    result = simulate_portfolio(
        trades,
        starting_capital=10_000.0,
        risk_per_trade_pct=0.5,
        max_open_positions=3,
        max_portfolio_risk_pct=1.5,
    )
    assert result["total_trades"] == 3
    assert result["signals_skipped"]["max_positions"] == 1


def test_portfolio_caps_correlated_positions() -> None:
    """BTC, ETH and SOL are one directional bet, not three."""
    trades = {
        "BTC/USDT": [_trade("BTC/USDT", 0, 100, 10.0)],
        "ETH/USDT": [_trade("ETH/USDT", 1, 100, 10.0)],
        "SOL/USDT": [_trade("SOL/USDT", 2, 100, 10.0)],
    }
    result = simulate_portfolio(
        trades,
        starting_capital=10_000.0,
        max_open_positions=3,
        max_per_correlation_group=2,
    )
    assert result["total_trades"] == 2
    assert result["signals_skipped"]["correlation"] == 1


def test_portfolio_accounts_for_sequential_trades() -> None:
    """Trades that do not overlap should all be taken."""
    trades = {
        "BTC/USDT": [
            _trade("BTC/USDT", 0, 10, 100.0),
            _trade("BTC/USDT", 20, 30, -50.0),
            _trade("BTC/USDT", 40, 50, 25.0),
        ]
    }
    result = simulate_portfolio(trades, starting_capital=1_000.0)
    assert result["total_trades"] == 3
    assert result["net_pnl"] == pytest.approx(75.0)
    assert result["final_balance"] == pytest.approx(1_075.0)
    assert result["win_rate_pct"] == pytest.approx(66.667, abs=0.01)


def test_buy_and_hold_benchmark() -> None:
    prices = np.linspace(100.0, 150.0, 500)
    frame = pd.DataFrame(
        {
            "open_time": [1_700_000_000_000 + i * 900_000 for i in range(500)],
            "open": prices,
            "high": prices * 1.001,
            "low": prices * 0.999,
            "close": prices,
            "volume": np.full(500, 100.0),
        }
    )
    result = buy_and_hold(frame, 10_000.0, "15m")
    assert result["total_return_pct"] == pytest.approx(50.0, abs=0.1)
    assert result["max_drawdown_pct"] == pytest.approx(0.0, abs=0.01)
