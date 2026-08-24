"""Run the full research pipeline for a strategy and print an honest report.

    .venv/Scripts/python.exe scripts/run_research.py --strategy adaptive_momentum

Pipeline, in this order and no other:

    baseline -> controlled optimisation (IN-SAMPLE ONLY)
             -> validation -> out-of-sample -> walk-forward
             -> Monte Carlo -> parameter stability -> benchmarks
             -> cost sensitivity

The optimisation never sees the validation or out-of-sample windows. The time
series is split chronologically and never shuffled.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
import time
from datetime import datetime
from typing import Any

import pandas as pd

from app.backtesting.costs import CostModel
from app.backtesting.engine import BacktestEngine, BacktestRequest
from app.backtesting.monte_carlo import run_monte_carlo
from app.backtesting.portfolio_sim import simulate_portfolio
from app.backtesting.research import buy_and_hold, cost_sensitivity, parameter_stability
from app.backtesting.walk_forward import WalkForwardRequest, run_walk_forward
from app.core.constants import DatasetSplit
from app.core.time_utils import from_ms
from app.database.session import SessionLocal
from app.market_data import store
from app.risk.config import RiskConfig
from app.strategies.registry import get_strategy_class

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
]

#: Markets used to choose parameters. Keeping this small and then validating on
#: every market is what stops the search from fitting nine curves at once.
OPTIMISATION_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

#: Minimum number of trades before a result is allowed to mean anything.
MIN_TRADES = 30
MAX_ACCEPTABLE_DRAWDOWN = 35.0


def load_frames(symbols: list[str], timeframe: str) -> dict[str, pd.DataFrame]:
    """Read the cached candles for each market."""
    frames: dict[str, pd.DataFrame] = {}
    with SessionLocal() as db:
        for symbol in symbols:
            frame = store.load_candles(db, symbol, timeframe)
            if frame.empty:
                print(f"  {symbol:12s} NO DATA, skipped")
                continue
            frames[symbol] = frame
    return frames


def split_frame(frame: pd.DataFrame, ratios: tuple[float, float, float]):
    """Chronological in-sample / validation / out-of-sample split."""
    total = len(frame)
    first = int(total * ratios[0])
    second = first + int(total * ratios[1])
    return (
        frame.iloc[:first].reset_index(drop=True),
        frame.iloc[first:second].reset_index(drop=True),
        frame.iloc[second:].reset_index(drop=True),
    )


def build_request(
    strategy_key: str,
    symbol: str,
    timeframe: str,
    params: dict[str, Any],
    args: argparse.Namespace,
    split: DatasetSplit = DatasetSplit.FULL,
) -> BacktestRequest:
    """One request object with the cost and risk model the study uses."""
    return BacktestRequest(
        strategy_key=strategy_key,
        symbol=symbol,
        timeframe=timeframe,
        start=datetime(2024, 1, 1),
        end=datetime(2026, 1, 1),
        starting_capital=args.capital,
        leverage=args.leverage,
        params=params,
        cost_model=CostModel(
            taker_fee_pct=args.fee,
            maker_fee_pct=args.fee / 2,
            slippage_pct=args.slippage,
            funding_rate_pct_per_8h=args.funding,
            apply_funding=True,
        ),
        risk=RiskConfig(
            risk_per_trade_pct=args.risk_per_trade,
            daily_loss_limit_pct=args.daily_loss_limit,
            daily_profit_target_pct=args.daily_profit_target,
            max_trades_per_day=args.max_trades_per_day,
            max_consecutive_losses=args.max_consecutive_losses,
            max_concurrent_positions=3,
            max_leverage=max(args.leverage, 1),
            max_drawdown_pct=args.max_drawdown,
            cooldown_minutes=args.cooldown_minutes,
            min_signal_confidence=0.0,
        ),
        split=split,
        respect_daily_limits=True,
    )


def run_on_frames(
    engine: BacktestEngine,
    frames: dict[str, pd.DataFrame],
    strategy_key: str,
    params: dict[str, Any],
    timeframe: str,
    args: argparse.Namespace,
    split: DatasetSplit = DatasetSplit.FULL,
) -> dict[str, Any]:
    """Run one configuration across several markets and aggregate the result."""
    per_symbol: dict[str, Any] = {}
    trades_by_symbol: dict[str, list[dict[str, Any]]] = {}

    for symbol, frame in frames.items():
        request = build_request(strategy_key, symbol, timeframe, params, args, split)
        try:
            output = engine.run(frame, request)
        except Exception as exc:
            per_symbol[symbol] = {"error": str(exc)[:160]}
            continue
        per_symbol[symbol] = output.metrics
        trades_by_symbol[symbol] = output.trades

    portfolio = simulate_portfolio(
        trades_by_symbol,
        starting_capital=args.capital,
        risk_per_trade_pct=args.risk_per_trade,
        max_open_positions=3,
        max_portfolio_risk_pct=args.max_portfolio_risk,
    )
    return {"per_symbol": per_symbol, "portfolio": portfolio, "trades": trades_by_symbol}


def objective(metrics: dict[str, Any]) -> float:
    """Rank configurations without letting net profit decide on its own.

    Hard gates first (enough trades, survivable drawdown, profit factor above
    one), then Sharpe as the ranking value. A configuration that fails a gate
    scores minus infinity rather than being quietly ranked low.
    """
    trades = float(metrics.get("total_trades") or 0)
    if trades < MIN_TRADES:
        return float("-inf")
    drawdown = float(metrics.get("max_drawdown_pct") or 0.0)
    if drawdown > MAX_ACCEPTABLE_DRAWDOWN:
        return float("-inf")
    profit_factor = metrics.get("profit_factor")
    if profit_factor is None or float(profit_factor) <= 1.0:
        return float("-inf")
    sharpe = metrics.get("sharpe_ratio")
    if sharpe is None:
        return float("-inf")
    return float(sharpe)


#: Coordinate search: one parameter group at a time, in order of importance.
#: A full grid over eleven parameters would be millions of combinations and
#: would fit noise. Sweeping one axis at a time also produces exactly the data
#: needed for the parameter stability report.
SEARCH_PLAN: list[tuple[str, list[dict[str, Any]]]] = [
    ("min_signal_score", [{"min_signal_score": v} for v in (60, 65, 70, 75, 80)]),
    ("atr_stop_multiplier", [{"atr_stop_multiplier": v} for v in (1.2, 1.3, 1.5, 1.7, 2.0)]),
    ("take_profit_r", [{"take_profit_r": v} for v in (1.5, 1.75, 2.0, 2.25, 2.5, 3.0)]),
    ("exit_model", [{"exit_model": v} for v in ("atr", "ema", "hybrid")]),
    ("min_adx", [{"min_adx": v} for v in (18, 20, 24, 28)]),
    ("volume_multiplier", [{"volume_multiplier": v} for v in (1.0, 1.2, 1.5, 2.0)]),
    (
        "ema_pair",
        [
            {"ema_fast": 10, "ema_slow": 30},
            {"ema_fast": 20, "ema_slow": 50},
            {"ema_fast": 30, "ema_slow": 80},
        ],
    ),
    ("breakout_lookback", [{"breakout_lookback": v} for v in (3, 5, 8, 10)]),
    ("min_atr_pct", [{"min_atr_pct": v} for v in (0.2, 0.3, 0.4, 0.5, 0.75)]),
    ("rsi_period", [{"rsi_period": v} for v in (10, 14, 21)]),
]


def optimise(
    engine: BacktestEngine,
    frames: dict[str, pd.DataFrame],
    strategy_key: str,
    baseline_params: dict[str, Any],
    timeframe: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Coordinate search on the IN-SAMPLE data only."""
    params = dict(baseline_params)
    history: list[dict[str, Any]] = []

    for axis, candidates in SEARCH_PLAN:
        best_score = float("-inf")
        best_override: dict[str, Any] | None = None
        axis_rows: list[dict[str, Any]] = []

        for override in candidates:
            trial = {**params, **override}
            result = run_on_frames(
                engine, frames, strategy_key, trial, timeframe, args, DatasetSplit.IN_SAMPLE
            )
            # The portfolio simulator has no Sharpe, so rank on the average of
            # the per-market Sharpe values weighted by trade count.
            metrics = _portfolio_metrics_with_sharpe(result)
            score = objective(metrics)
            axis_rows.append(
                {
                    "override": override,
                    "score": None if score == float("-inf") else round(score, 3),
                    "return_pct": round(metrics.get("total_return_pct") or 0.0, 2),
                    "profit_factor": _round(metrics.get("profit_factor")),
                    "sharpe": _round(metrics.get("sharpe_ratio")),
                    "max_dd_pct": round(metrics.get("max_drawdown_pct") or 0.0, 2),
                    "trades": int(metrics.get("total_trades") or 0),
                }
            )
            if score > best_score:
                best_score = score
                best_override = override

        history.append({"axis": axis, "rows": axis_rows, "chosen": best_override})
        if best_override is not None and best_score > float("-inf"):
            params.update(best_override)
        label = round(best_score, 3) if best_score > float("-inf") else "rejected"
        print(f"  {axis:20s} -> {best_override} (score {label})")

    return params, history


def _portfolio_metrics_with_sharpe(result: dict[str, Any]) -> dict[str, Any]:
    """Combine the portfolio result with a trade-weighted average Sharpe."""
    metrics = dict(result["portfolio"])
    weighted_sum = 0.0
    weight_total = 0.0
    for symbol_metrics in result["per_symbol"].values():
        if not isinstance(symbol_metrics, dict) or "sharpe_ratio" not in symbol_metrics:
            continue
        sharpe = symbol_metrics.get("sharpe_ratio")
        trades = float(symbol_metrics.get("total_trades") or 0)
        if sharpe is None or trades <= 0:
            continue
        weighted_sum += float(sharpe) * trades
        weight_total += trades
    metrics["sharpe_ratio"] = (weighted_sum / weight_total) if weight_total else None
    return metrics


def _round(value: Any, digits: int = 3) -> Any:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def summarise(label: str, metrics: dict[str, Any]) -> str:
    """One line per result, always with the numbers that can hurt you."""
    return (
        f"{label:<26} return {metrics.get('total_return_pct', 0):7.2f}%  "
        f"PF {_fmt(metrics.get('profit_factor')):>5}  "
        f"Sharpe {_fmt(metrics.get('sharpe_ratio')):>6}  "
        f"maxDD {metrics.get('max_drawdown_pct', 0):6.2f}%  "
        f"trades {int(metrics.get('total_trades') or 0):5d}  "
        f"win {metrics.get('win_rate_pct', 0):5.1f}%"
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy research pipeline")
    parser.add_argument("--strategy", default="adaptive_momentum")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--leverage", type=int, default=3)
    parser.add_argument("--fee", type=float, default=0.05)
    parser.add_argument("--slippage", type=float, default=0.05)
    parser.add_argument("--funding", type=float, default=0.01)
    parser.add_argument("--risk-per-trade", type=float, default=0.5)
    parser.add_argument("--max-portfolio-risk", type=float, default=1.5)
    parser.add_argument("--daily-loss-limit", type=float, default=2.0)
    parser.add_argument("--daily-profit-target", type=float, default=100.0)
    parser.add_argument("--max-trades-per-day", type=int, default=20)
    parser.add_argument("--cooldown-minutes", type=int, default=45)
    parser.add_argument("--max-consecutive-losses", type=int, default=3)
    # A study must observe the whole period. The production config keeps the
    # 15 percent account circuit breaker; halting the simulation on it would
    # truncate every losing configuration and make comparisons meaningless.
    parser.add_argument("--max-drawdown", type=float, default=95.0)
    parser.add_argument("--skip-optimisation", action="store_true")
    parser.add_argument("--output", default="research_report.json")
    args = parser.parse_args()

    engine = BacktestEngine()
    report: dict[str, Any] = {"strategy": args.strategy, "settings": vars(args)}

    print("=" * 78)
    print(f"RESEARCH PIPELINE - {args.strategy} - {args.timeframe}")
    print("=" * 78)
    print(
        f"Costs: taker {args.fee}%, slippage {args.slippage}%, "
        f"funding {args.funding}%/8h, leverage {args.leverage}x, "
        f"risk/trade {args.risk_per_trade}%"
    )

    print("\n[1/9] Loading cached candles")
    frames = load_frames(SYMBOLS, args.timeframe)
    if not frames:
        print("No data. Run scripts/download_history.py first.")
        return
    for symbol, frame in frames.items():
        first = from_ms(int(frame["open_time"].iloc[0])).date()
        last = from_ms(int(frame["open_time"].iloc[-1])).date()
        print(f"  {symbol:12s} {len(frame):7,} candles  {first} to {last}")
    report["data"] = {symbol: {"candles": len(frame)} for symbol, frame in frames.items()}

    splits = {symbol: split_frame(frame, (0.6, 0.2, 0.2)) for symbol, frame in frames.items()}
    in_sample = {symbol: parts[0] for symbol, parts in splits.items()}
    validation = {symbol: parts[1] for symbol, parts in splits.items()}
    out_of_sample = {symbol: parts[2] for symbol, parts in splits.items()}

    baseline_params = get_strategy_class(args.strategy).default_params()

    print("\n[2/9] Baseline on the full period (default parameters)")
    started = time.perf_counter()
    baseline_full = run_on_frames(
        engine, frames, args.strategy, baseline_params, args.timeframe, args
    )
    print(f"  simulated in {time.perf_counter() - started:.1f}s")
    for symbol, metrics in baseline_full["per_symbol"].items():
        if "error" in metrics:
            print(f"  {symbol:12s} ERROR {metrics['error']}")
        else:
            print("  " + summarise(symbol, metrics))
    print("  " + summarise("PORTFOLIO", _portfolio_metrics_with_sharpe(baseline_full)))
    report["baseline_full"] = {
        "per_symbol": baseline_full["per_symbol"],
        "portfolio": {
            key: value
            for key, value in baseline_full["portfolio"].items()
            if key not in ("equity_curve", "trade_returns")
        },
    }

    # ---------------------------------------------------------------- 3/9 --
    if args.skip_optimisation:
        chosen_params = dict(baseline_params)
        search_history: list[dict[str, Any]] = []
        print("\n[3/9] Optimisation skipped, using the baseline parameters")
    else:
        print("\n[3/9] Coordinate search on IN-SAMPLE data only")
        print(f"  markets used for the search: {', '.join(OPTIMISATION_SYMBOLS)}")
        search_frames = {
            symbol: in_sample[symbol] for symbol in OPTIMISATION_SYMBOLS if symbol in in_sample
        }
        started = time.perf_counter()
        chosen_params, search_history = optimise(
            engine, search_frames, args.strategy, baseline_params, args.timeframe, args
        )
        print(f"  search finished in {time.perf_counter() - started:.1f}s")
    report["chosen_params"] = chosen_params
    report["search_history"] = search_history

    # ---------------------------------------------------------------- 4/9 --
    print("\n[4/9] VALIDATION window (parameters were chosen without seeing it)")
    validation_result = run_on_frames(
        engine,
        validation,
        args.strategy,
        chosen_params,
        args.timeframe,
        args,
        DatasetSplit.VALIDATION,
    )
    print("  " + summarise("PORTFOLIO", _portfolio_metrics_with_sharpe(validation_result)))
    report["validation"] = {
        "per_symbol": validation_result["per_symbol"],
        "portfolio": _strip(validation_result["portfolio"]),
    }

    # ---------------------------------------------------------------- 5/9 --
    print("\n[5/9] OUT-OF-SAMPLE window (the only numbers that carry information)")
    oos_baseline = run_on_frames(
        engine,
        out_of_sample,
        args.strategy,
        baseline_params,
        args.timeframe,
        args,
        DatasetSplit.OUT_OF_SAMPLE,
    )
    oos_tuned = run_on_frames(
        engine,
        out_of_sample,
        args.strategy,
        chosen_params,
        args.timeframe,
        args,
        DatasetSplit.OUT_OF_SAMPLE,
    )
    print("  " + summarise("baseline params", _portfolio_metrics_with_sharpe(oos_baseline)))
    print("  " + summarise("tuned params", _portfolio_metrics_with_sharpe(oos_tuned)))
    for symbol, metrics in oos_tuned["per_symbol"].items():
        if "error" not in metrics:
            print("    " + summarise(symbol, metrics))
    report["out_of_sample"] = {
        "baseline": _strip(oos_baseline["portfolio"]),
        "tuned": _strip(oos_tuned["portfolio"]),
        "tuned_per_symbol": oos_tuned["per_symbol"],
    }

    # ---------------------------------------------------------------- 6/9 --
    print("\n[6/9] Walk-forward analysis on BTC/USDT and ETH/USDT")
    walk_forward: dict[str, Any] = {}
    for symbol in ("BTC/USDT", "ETH/USDT"):
        if symbol not in frames:
            continue
        request = build_request(args.strategy, symbol, args.timeframe, chosen_params, args)
        try:
            result = run_walk_forward(
                frames[symbol],
                request,
                WalkForwardRequest(
                    folds=4,
                    in_sample_ratio=0.7,
                    param_grid={"min_signal_score": [65, 70, 75]},
                    objective="sharpe_ratio",
                    min_trades=10,
                ),
                engine,
            )
        except Exception as exc:
            print(f"  {symbol}: {exc}")
            continue
        walk_forward[symbol] = result
        summary = result["out_of_sample_summary"]
        print(
            f"  {symbol:12s} folds {summary.get('folds_evaluated', 0)}, "
            f"profitable {summary.get('profitable_folds', 0)}, "
            f"avg OOS return {_fmt(summary.get('total_return_pct'))}%, "
            f"avg OOS Sharpe {_fmt(summary.get('sharpe_ratio'))}"
        )
    report["walk_forward"] = walk_forward

    # ---------------------------------------------------------------- 7/9 --
    print("\n[7/9] Monte Carlo on the out-of-sample trades (10,000 simulations)")
    oos_returns = oos_tuned["portfolio"]["trade_returns"]
    monte_carlo = run_monte_carlo(oos_returns, args.capital, simulations=10_000)
    if monte_carlo.get("ran"):
        print(
            f"  median {monte_carlo['median_return_pct']:6.2f}%   "
            f"5th {monte_carlo['return_p5_pct']:6.2f}%   "
            f"95th {monte_carlo['return_p95_pct']:6.2f}%"
        )
        print(
            f"  median maxDD {monte_carlo['median_max_drawdown_pct']:5.2f}%   "
            f"worst {monte_carlo['worst_drawdown_pct']:5.2f}%   "
            f"P(profit) {monte_carlo['probability_of_profit_pct']:5.1f}%   "
            f"worst losing streak {monte_carlo['worst_losing_streak']}"
        )
    else:
        print(f"  {monte_carlo.get('reason')}")
    report["monte_carlo"] = monte_carlo

    # ---------------------------------------------------------------- 8/9 --
    print("\n[8/9] Parameter stability on BTC/USDT (in-sample)")
    stability: dict[str, Any] = {}
    if "BTC/USDT" in in_sample:
        base = build_request(
            args.strategy, "BTC/USDT", args.timeframe, chosen_params, args, DatasetSplit.IN_SAMPLE
        )
        sweeps = {
            "min_signal_score": [60, 65, 70, 75, 80],
            "atr_stop_multiplier": [1.2, 1.3, 1.5, 1.7, 2.0],
            "take_profit_r": [1.5, 1.75, 2.0, 2.25, 2.5, 3.0],
            "ema_fast": [16, 18, 20, 22, 24],
        }
        for parameter, values in sweeps.items():
            result = parameter_stability(
                in_sample["BTC/USDT"], base, parameter, values, "profit_factor", engine
            )
            stability[parameter] = result
            cells = " ".join(f"{row['value']}:{_fmt(row['metric'])}" for row in result["rows"])
            print(f"  {parameter:20s} {cells}")
            print(f"  {'':20s} -> {result['verdict']}")
    report["parameter_stability"] = stability

    # ---------------------------------------------------------------- 9/9 --
    print("\n[9/9] Benchmarks and cost sensitivity")
    benchmarks: dict[str, Any] = {}
    for symbol in ("BTC/USDT", "ETH/USDT"):
        if symbol in out_of_sample:
            benchmarks[f"buy_and_hold_{symbol}"] = buy_and_hold(
                out_of_sample[symbol], args.capital, args.timeframe
            )
    for reference in ("trend_following", "mean_reversion", "macd_momentum"):
        try:
            other = run_on_frames(
                engine,
                out_of_sample,
                reference,
                get_strategy_class(reference).default_params(),
                args.timeframe,
                args,
                DatasetSplit.OUT_OF_SAMPLE,
            )
            benchmarks[reference] = _strip(other["portfolio"])
        except Exception as exc:
            benchmarks[reference] = {"error": str(exc)[:160]}
    for label, metrics in benchmarks.items():
        if "error" in metrics:
            print(f"  {label:26s} ERROR")
        else:
            print("  " + summarise(label, metrics))
    report["benchmarks"] = benchmarks

    sensitivity = {}
    if "BTC/USDT" in out_of_sample:
        base = build_request(
            args.strategy,
            "BTC/USDT",
            args.timeframe,
            chosen_params,
            args,
            DatasetSplit.OUT_OF_SAMPLE,
        )
        sensitivity = cost_sensitivity(
            out_of_sample["BTC/USDT"], base, [0.02, 0.05, 0.10, 0.15], engine
        )
        for row in sensitivity["rows"]:
            print(
                f"  slippage {row['slippage_pct']:.2f}%  "
                f"return {_fmt(row['total_return_pct']):>7}%  "
                f"PF {_fmt(row['profit_factor']):>5}  trades {row['total_trades']}"
            )
        print(f"  -> {sensitivity['verdict']}")
    report["cost_sensitivity"] = sensitivity

    output_path = Path(args.output)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nFull report written to {output_path.resolve()}")


def _strip(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Drop the bulky series before a result goes into the JSON report."""
    return {
        key: value
        for key, value in portfolio.items()
        if key not in ("equity_curve", "trade_returns")
    }


if __name__ == "__main__":
    main()
