"""Conditional expectancy: which signals were worth the toll."""

from __future__ import annotations

import pytest

from app.backtesting.signal_quality import MIN_TRADES_PER_BUCKET, analyse


def trade(r: float, *, confidence=0.5, trend="RANGING", adx=25.0, hour=10, side="LONG"):
    return {
        "r_multiple": r,
        "is_win": r > 0,
        "side": side,
        "market_regime": trend,
        "entry_context": {
            "confidence": confidence,
            "trend": trend,
            "volatility": "NORMAL",
            "adx": adx,
            "atr_pct": 1.0,
            "volatility_rank": 0.5,
            "hour_utc": hour,
            "stop_distance_pct": 2.0,
        },
    }


class TestBaseline:
    def test_no_trades_is_reported_not_crashed(self) -> None:
        report = analyse([])
        assert report.total_trades == 0
        assert report.notes

    def test_baseline_is_the_average_of_every_trade(self) -> None:
        report = analyse([trade(1.0), trade(-1.0), trade(0.5)])
        assert report.baseline_expectancy_r == pytest.approx(0.5 / 3)

    def test_trades_without_an_r_multiple_are_ignored(self) -> None:
        rows = [trade(1.0), {"is_win": True}]
        assert analyse(rows).total_trades == 1


class TestBucketing:
    def test_a_thin_bucket_is_not_reported(self) -> None:
        """Slicing a small sample finds a profitable pocket every time, and it
        is noise. Buckets under the minimum simply do not appear."""
        rows = [trade(1.0, trend="TRENDING_UP") for _ in range(5)]
        rows += [trade(-1.0, trend="RANGING") for _ in range(5)]
        report = analyse(rows)
        assert report.buckets == []
        assert report.notes

    def test_a_real_split_is_found(self) -> None:
        rows = [trade(1.0, confidence=0.9) for _ in range(60)]
        rows += [trade(-1.0, confidence=0.4) for _ in range(60)]
        report = analyse(rows, min_trades=20)
        confidence_buckets = [b for b in report.buckets if b.feature == "confidence"]
        assert confidence_buckets
        best = max(confidence_buckets, key=lambda b: b.expectancy_r)
        assert best.expectancy_r > 0

    def test_edge_is_measured_against_taking_everything(self) -> None:
        rows = [trade(2.0, trend="TRENDING_UP") for _ in range(40)]
        rows += [trade(-1.0, trend="RANGING") for _ in range(40)]
        report = analyse(rows, min_trades=20)
        good = next(b for b in report.buckets if b.label == "TRENDING_UP")
        assert good.edge_vs_all == pytest.approx(good.expectancy_r - report.baseline_expectancy_r)

    def test_sessions_are_split_by_utc_hour(self) -> None:
        rows = [trade(1.0, hour=3) for _ in range(40)]
        rows += [trade(-1.0, hour=20) for _ in range(40)]
        report = analyse(rows, min_trades=20)
        sessions = {b.label for b in report.buckets if b.feature == "session"}
        assert "Asia 00-08 UTC" in sessions
        assert "US 16-24 UTC" in sessions

    def test_best_and_worst_are_ordered(self) -> None:
        rows = [trade(2.0, trend="TRENDING_UP") for _ in range(40)]
        rows += [trade(-2.0, trend="RANGING") for _ in range(40)]
        report = analyse(rows, min_trades=20)
        assert report.best(1)[0].edge_vs_all >= report.worst(1)[0].edge_vs_all

    def test_the_default_minimum_is_conservative(self) -> None:
        assert MIN_TRADES_PER_BUCKET >= 30
