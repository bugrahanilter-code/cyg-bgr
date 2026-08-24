"""Picking a strategy and timeframe without fooling yourself."""

from __future__ import annotations

from datetime import UTC

from app.core.constants import BacktestStatus
from app.models.sweep import BacktestSweep, SweepRun
from app.services.strategy_selection import SelectionCriteria, select_best


def _sweep(db) -> BacktestSweep:
    import uuid
    from datetime import datetime, timedelta

    end = datetime(2026, 8, 1, tzinfo=UTC)
    record = BacktestSweep(
        uid=uuid.uuid4().hex[:24],
        name="selection test",
        strategy_keys=["good", "narrow"],
        symbols=[f"C{i}/USDT" for i in range(8)],
        timeframes=["1h"],
        start_date=end - timedelta(days=365),
        end_date=end,
        total_runs=16,
        status=BacktestStatus.COMPLETED.value,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _cell(sweep_id, strategy, timeframe, symbol, *, expectancy, pnl, trades=60, pf=1.2, dd=10.0):
    return SweepRun(
        sweep_id=sweep_id,
        strategy_key=strategy,
        timeframe=timeframe,
        symbol=symbol,
        status=BacktestStatus.COMPLETED.value,
        total_trades=trades,
        net_pnl=pnl,
        return_pct=pnl / 100.0,
        buy_hold_return_pct=0.0,
        expectancy_r=expectancy,
        profit_factor=pf,
        max_drawdown_pct=dd,
    )


class TestSelection:
    def test_a_broad_consistent_winner_is_accepted(self, db) -> None:
        sweep = _sweep(db)
        for index in range(8):
            db.add(_cell(sweep.id, "good", "1h", f"C{index}/USDT", expectancy=0.05, pnl=200.0))
        db.commit()

        result = select_best(db, sweep.id)
        assert result["verdict"] == "QUALIFIED"
        assert result["winner"]["strategy_key"] == "good"
        assert result["winner"]["profitable_pct"] == 100.0

    def test_one_lucky_market_does_not_qualify(self, db) -> None:
        """A combination carried by a single outlier is the classic false
        positive, so breadth is scored on the median market."""
        sweep = _sweep(db)
        db.add(_cell(sweep.id, "narrow", "1h", "C0/USDT", expectancy=2.0, pnl=9_000.0))
        for index in range(1, 8):
            db.add(_cell(sweep.id, "narrow", "1h", f"C{index}/USDT", expectancy=-0.08, pnl=-150.0))
        db.commit()

        result = select_best(db, sweep.id)
        assert result["verdict"] == "NO_QUALIFYING_COMBINATION"
        narrow = next(r for r in result["ranked"] if r["strategy_key"] == "narrow")
        assert narrow["passed"] is False
        assert any("profitable on" in reason for reason in narrow["failures"])

    def test_too_few_trades_is_rejected(self, db) -> None:
        sweep = _sweep(db)
        for index in range(8):
            db.add(
                _cell(
                    sweep.id,
                    "good",
                    "1h",
                    f"C{index}/USDT",
                    expectancy=0.4,
                    pnl=500.0,
                    trades=6,
                )
            )
        db.commit()
        result = select_best(db, sweep.id)
        assert result["verdict"] == "NO_QUALIFYING_COMBINATION"

    def test_no_winner_is_a_verdict_not_an_error(self, db) -> None:
        """Handing back the least bad row is how a losing configuration ends up
        trading, so nothing is returned when nothing qualifies."""
        sweep = _sweep(db)
        for index in range(8):
            db.add(_cell(sweep.id, "bad", "1h", f"C{index}/USDT", expectancy=-0.2, pnl=-400.0))
        db.commit()

        result = select_best(db, sweep.id)
        assert result["verdict"] == "NO_QUALIFYING_COMBINATION"
        assert result["winner"] is None
        assert result["ranked"], "the ranking is still returned for inspection"

    def test_the_selection_bias_warning_is_always_present(self, db) -> None:
        sweep = _sweep(db)
        for index in range(8):
            db.add(_cell(sweep.id, "good", "1h", f"C{index}/USDT", expectancy=0.05, pnl=200.0))
        db.commit()
        result = select_best(db, sweep.id)
        assert "inflated by chance" in result["selection_bias_note"]
        assert result["combinations_tested"] >= 1

    def test_a_huge_drawdown_disqualifies(self, db) -> None:
        sweep = _sweep(db)
        for index in range(8):
            db.add(
                _cell(
                    sweep.id,
                    "wild",
                    "1h",
                    f"C{index}/USDT",
                    expectancy=0.3,
                    pnl=900.0,
                    dd=80.0,
                )
            )
        db.commit()
        result = select_best(db, sweep.id, SelectionCriteria(max_median_drawdown_pct=35.0))
        assert result["verdict"] == "NO_QUALIFYING_COMBINATION"
        wild = next(r for r in result["ranked"] if r["strategy_key"] == "wild")
        assert any("drawdown" in reason for reason in wild["failures"])
