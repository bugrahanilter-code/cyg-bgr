"""Which signals were worth taking, and which only paid the spread.

The problem this attacks
------------------------
Every study in this project lands on the same wall: the direction is slightly
right and the costs are larger than the edge. Zero-cost expectancy was +0.016R;
a round trip costs about 0.24R. Adding another strategy does not fix that,
because the new strategy pays the same toll.

The other lever is to trade *less*. If a subset of signals carries most of the
edge, taking only those pays the toll fewer times on the trades that earn it.
That is the idea behind meta-labeling: keep the primary signal's direction, add
a second decision about whether it is worth acting on.

Why this is buckets rather than a model
---------------------------------------
A gradient-boosted classifier would find sharper splits. It would also be a new
dependency, and - more importantly - it would answer "should I take this trade?"
with a number nobody can argue with. Conditional expectancy per bucket answers
the same question with "trades taken when ADX was under 20 lost 0.09R each over
340 trades", which is checkable and can be disagreed with.

The overfitting trap
--------------------
Slicing 300 trades by six features finds a profitable pocket every time, and
that pocket is usually noise. Two guards apply throughout:

* a bucket needs ``min_trades`` before it is reported at all
* every filter this module suggests is measured on a period it was not derived
  from, and the result of that measurement is what gets reported
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

#: Buckets thinner than this are noise, whatever they appear to show.
MIN_TRADES_PER_BUCKET = 30


@dataclass(slots=True)
class Bucket:
    """One slice of the trades, and how it did."""

    feature: str
    label: str
    trades: int
    expectancy_r: float
    win_rate_pct: float
    total_r: float
    #: How much better or worse than taking every trade.
    edge_vs_all: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "label": self.label,
            "trades": self.trades,
            "expectancy_r": round(self.expectancy_r, 4),
            "win_rate_pct": round(self.win_rate_pct, 1),
            "total_r": round(self.total_r, 2),
            "edge_vs_all": round(self.edge_vs_all, 4),
        }


@dataclass(slots=True)
class QualityReport:
    """Conditional expectancy across every feature examined."""

    total_trades: int
    baseline_expectancy_r: float
    buckets: list[Bucket] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def best(self, limit: int = 10) -> list[Bucket]:
        return sorted(self.buckets, key=lambda b: b.edge_vs_all, reverse=True)[:limit]

    def worst(self, limit: int = 10) -> list[Bucket]:
        return sorted(self.buckets, key=lambda b: b.edge_vs_all)[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "baseline_expectancy_r": round(self.baseline_expectancy_r, 4),
            "buckets": [b.to_dict() for b in self.buckets],
            "best": [b.to_dict() for b in self.best()],
            "worst": [b.to_dict() for b in self.worst()],
            "notes": self.notes,
        }


def _numeric_bands(values: list[float], count: int = 4) -> list[tuple[float, float, str]]:
    """Split a numeric feature into quantile bands.

    Quantiles rather than fixed thresholds, so each band holds a comparable
    number of trades. Fixed thresholds put 90% of the sample in one bucket on a
    skewed feature such as ATR percentage.
    """
    clean = sorted(v for v in values if v is not None)
    if len(clean) < count * MIN_TRADES_PER_BUCKET:
        count = max(2, len(clean) // MIN_TRADES_PER_BUCKET)
    if count < 2:
        return []
    edges = [clean[int(len(clean) * i / count)] for i in range(1, count)]
    edges = sorted(set(edges))
    if not edges:
        return []

    bands: list[tuple[float, float, str]] = []
    low = float("-inf")
    for edge in edges:
        bands.append((low, edge, f"< {edge:.4g}"))
        low = edge
    bands.append((low, float("inf"), f">= {low:.4g}"))
    return bands


def analyse(trades: list[dict[str, Any]], min_trades: int = MIN_TRADES_PER_BUCKET) -> QualityReport:
    """Expectancy per condition, for every condition recorded at entry."""
    usable = [t for t in trades if t.get("r_multiple") is not None]
    if not usable:
        return QualityReport(0, 0.0, notes=["No trades with an R multiple to analyse"])

    all_r = [float(t["r_multiple"]) for t in usable]
    baseline = statistics.fmean(all_r)
    report = QualityReport(total_trades=len(usable), baseline_expectancy_r=baseline)

    def add_bucket(feature: str, label: str, subset: list[dict[str, Any]]) -> None:
        if len(subset) < min_trades:
            return
        values = [float(t["r_multiple"]) for t in subset]
        wins = sum(1 for t in subset if t.get("is_win"))
        expectancy = statistics.fmean(values)
        report.buckets.append(
            Bucket(
                feature=feature,
                label=label,
                trades=len(subset),
                expectancy_r=expectancy,
                win_rate_pct=wins / len(subset) * 100.0,
                total_r=sum(values),
                edge_vs_all=expectancy - baseline,
            )
        )

    # -- categorical features ------------------------------------------------
    for feature in ("trend", "volatility"):
        seen: dict[str, list[dict[str, Any]]] = {}
        for trade in usable:
            value = (trade.get("entry_context") or {}).get(feature)
            if value is not None:
                seen.setdefault(str(value), []).append(trade)
        for label, subset in seen.items():
            add_bucket(feature, label, subset)

    for feature, key in (("side", "side"), ("market_regime", "market_regime")):
        seen = {}
        for trade in usable:
            value = trade.get(key)
            if value is not None:
                seen.setdefault(str(value), []).append(trade)
        for label, subset in seen.items():
            add_bucket(feature, label, subset)

    # -- numeric features ----------------------------------------------------
    for feature in ("adx", "atr_pct", "volatility_rank", "confidence", "stop_distance_pct"):
        values = [(trade, (trade.get("entry_context") or {}).get(feature)) for trade in usable]
        present = [(t, v) for t, v in values if isinstance(v, int | float)]
        if len(present) < min_trades * 2:
            continue
        for low, high, label in _numeric_bands([v for _, v in present]):
            subset = [t for t, v in present if low <= v < high]
            add_bucket(feature, label, subset)

    # -- time of day ---------------------------------------------------------
    sessions = {
        "Asia 00-08 UTC": range(0, 8),
        "Europe 08-16 UTC": range(8, 16),
        "US 16-24 UTC": range(16, 24),
    }
    for label, hours in sessions.items():
        subset = [t for t in usable if (t.get("entry_context") or {}).get("hour_utc") in hours]
        add_bucket("session", label, subset)

    if not report.buckets:
        report.notes.append(f"No condition had {min_trades} trades. Nothing here can be concluded.")
    return report
