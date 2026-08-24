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


def _trade(symbol: str, opened: int, closed: int, r_multiple: float) -> dict:
    """A closed trade expressed in R-multiples, which is how a portfolio replays it."""
    return {
        "symbol": symbol,
        "opened_ms": opened,
        "closed_ms": closed,
        "net_pnl": r_multiple * 100.0,
        "risk_amount": 100.0,
        "r_multiple": r_multiple,
    }


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


def test_portfolio_compounds_r_multiples_on_one_account() -> None:
    """Non-overlapping trades are all taken and compound on shared equity."""
    trades = {
        "BTC/USDT": [
            _trade("BTC/USDT", 0, 10, 2.0),
            _trade("BTC/USDT", 20, 30, -1.0),
            _trade("BTC/USDT", 40, 50, 1.0),
        ]
    }
    result = simulate_portfolio(trades, starting_capital=10_000.0, risk_per_trade_pct=1.0)
    # +2R on 1 percent risk, then -1R, then +1R, each on the running equity.
    expected = 10_000.0
    expected += 2.0 * 0.01 * expected
    expected += -1.0 * 0.01 * expected
    expected += 1.0 * 0.01 * expected

    assert result["total_trades"] == 3
    assert result["final_balance"] == pytest.approx(expected)
    assert result["win_rate_pct"] == pytest.approx(66.667, abs=0.01)


def test_portfolio_does_not_add_up_separate_accounts() -> None:
    """Regression test for a genuinely wrong number.

    Each market is simulated on its own account. Adding those PnL figures up
    made nine accounts losing 90 percent look like one account losing 810
    percent, which is impossible. Replaying in R-multiples keeps the loss on
    one account inside the only range it can be.
    """
    losing_run = [_trade("BTC/USDT", i * 100, i * 100 + 50, -1.0) for i in range(60)]
    second_market = [_trade("XRP/USDT", i * 100 + 10, i * 100 + 60, -1.0) for i in range(60)]
    result = simulate_portfolio(
        {"BTC/USDT": losing_run, "XRP/USDT": second_market},
        starting_capital=10_000.0,
        risk_per_trade_pct=1.0,
    )
    assert result["total_return_pct"] > -100.0
    assert result["final_balance"] > 0.0
    assert result["max_drawdown_pct"] <= 100.0


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


def test_monte_carlo_cannot_lose_more_than_the_account() -> None:
    """Regression test: percentiles reported losses worse than -100 percent.

    Summing trade PnL without a floor let simulated equity go negative, which
    is not a possible outcome for a cash account. Once the account is wiped it
    stays at zero.
    """
    ruinous = [-500.0] * 60
    result = run_monte_carlo(ruinous, starting_capital=10_000.0, simulations=500)

    assert result["return_p5_pct"] >= -100.0
    assert result["median_return_pct"] >= -100.0
    assert result["worst_drawdown_pct"] <= 100.0
    assert result["risk_of_ruin_pct"] == pytest.approx(100.0)
