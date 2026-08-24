"""Automatic rotation into the strongest 24 hour movers.

What it does
------------
On a schedule it ranks every tradable market by 24 hour change, takes the top N
that pass a set of quality filters, and makes that the enabled trading set.

What to know before switching it on
-----------------------------------
This is momentum chasing on a one-day lookback, and it has two costs that are
easy to miss:

* **Churn.** A market that leaves the list is closed and a new one is opened.
  Every rotation therefore pays entry and exit costs on the markets that moved,
  and transaction cost is the single factor that has beaten every strategy
  studied on this platform so far. A one hour interval over twenty markets can
  easily turn over the whole book in a day.
* **The move already happened.** A coin appears in the list *because* it rose
  24%. Nothing here predicts that it will continue.

None of that makes it useless - it is a legitimate, widely used selection rule -
but it is a selection rule, not an edge, and the results should be read that
way. It ships **disabled**, and the first thing it does when switched on is a
dry run.

Safety rules that are not configurable
--------------------------------------
* A market with an open position is never disabled. It stays enabled until the
  position is flat, so the engine can still manage the exit.
* Research-only markets (EUR/USD, USD/JPY) can never be selected.
* A market removed in the last ``cooldown_hours`` is not re-added, so a coin
  hovering at rank 20 does not thrash in and out every hour.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.market_data import reference_markets
from app.models.rotation import RotationRun
from app.models.trading import Position
from app.services import settings_service

logger = get_logger(__name__)

ROTATION_CONFIG_KEY = "rotation_config"


class RotationConfig(BaseModel):
    """Everything the rotation is allowed to decide for itself."""

    #: Off by default: this changes what the bot trades without being asked.
    enabled: bool = False
    #: Report what it would do instead of doing it. On until explicitly cleared.
    dry_run: bool = True

    top_n: int = Field(default=20, ge=1, le=100)
    interval_minutes: int = Field(default=60, ge=15, le=1440)

    # -- quality filters ----------------------------------------------------
    #: A market that pumped 300% on $2m of turnover cannot absorb an order.
    min_quote_volume_24h: float = Field(default=50_000_000.0, ge=0.0)
    #: A wide spread is a cost paid on every entry and every exit.
    max_spread_pct: float = Field(default=0.15, ge=0.0, le=5.0)
    #: A coin listed last week has no history to backtest against.
    min_listing_age_days: int = Field(default=30, ge=0, le=3650)
    #: Ignore moves so large they are usually a listing event or a wick.
    max_change_24h_pct: float = Field(default=100.0, ge=0.0, le=10_000.0)
    #: Require an actual rise: a "top gainer" list in a red market otherwise
    #: fills up with the coins that fell least.
    min_change_24h_pct: float = Field(default=0.0, ge=-100.0, le=100.0)

    # -- churn control ------------------------------------------------------
    cooldown_hours: int = Field(default=4, ge=0, le=168)
    #: Never swap more than this many markets in one pass.
    max_changes_per_run: int = Field(default=10, ge=1, le=100)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def get_config(db: Session) -> RotationConfig:
    stored = settings_service.get_json_setting(db, ROTATION_CONFIG_KEY, {})
    if not stored:
        config = RotationConfig()
        settings_service.set_json_setting(
            db, ROTATION_CONFIG_KEY, config.model_dump(mode="json"), "Market rotation"
        )
        return config
    try:
        return RotationConfig(**stored)
    except Exception:  # pragma: no cover - defensive against a hand-edited row
        logger.warning("Stored rotation config invalid, using defaults")
        return RotationConfig()


def save_config(db: Session, config: RotationConfig) -> RotationConfig:
    settings_service.set_json_setting(
        db, ROTATION_CONFIG_KEY, config.model_dump(mode="json"), "Market rotation"
    )
    return config


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------
def rank_candidates(
    rows: list[dict[str, Any]], config: RotationConfig
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the universe into accepted candidates and rejections with reasons.

    Returns ``(accepted, rejected)``. The rejections are kept because "why is
    this coin not in the list" is the first question anyone asks, and answering
    it from a stored reason beats re-deriving it later.
    """
    now_ms = int(utcnow().timestamp() * 1000)
    min_age_ms = config.min_listing_age_days * 86_400_000

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for row in rows:
        symbol = row.get("symbol", "")
        reason = _rejection_reason(row, config, now_ms, min_age_ms)
        if reason:
            rejected.append(
                {
                    "symbol": symbol,
                    "reason": reason,
                    "change_24h_pct": row.get("change_24h_pct"),
                    "quote_volume_24h": row.get("quote_volume_24h"),
                }
            )
            continue
        accepted.append(
            {
                "symbol": symbol,
                "change_24h_pct": float(row.get("change_24h_pct") or 0.0),
                "quote_volume_24h": float(row.get("quote_volume_24h") or 0.0),
                "spread_pct": row.get("spread_pct"),
                "last_price": row.get("last_price"),
            }
        )

    accepted.sort(key=lambda item: item["change_24h_pct"], reverse=True)
    for rank, item in enumerate(accepted, start=1):
        item["rank"] = rank
    return accepted, rejected


def _rejection_reason(
    row: dict[str, Any], config: RotationConfig, now_ms: int, min_age_ms: int
) -> str | None:
    """Why this market cannot be auto-enabled, or None if it can."""
    symbol = row.get("symbol", "")

    if not row.get("tradable", True):
        return "research-only market"
    if not reference_markets.is_tradable(symbol):
        return "research-only market"
    if row.get("kind") not in (None, "crypto"):
        # Gold is tradable but it is not a "top gainer" candidate; rotating into
        # a commodity because it moved 3% is not what this rule is for.
        return f"not a crypto market ({row.get('kind')})"

    change = row.get("change_24h_pct")
    if change is None:
        return "no 24h change reported"
    if change < config.min_change_24h_pct:
        return f"24h change {change:.1f}% below the {config.min_change_24h_pct:.1f}% floor"
    if change > config.max_change_24h_pct:
        return (
            f"24h change {change:.1f}% above the {config.max_change_24h_pct:.0f}% ceiling, "
            "usually a listing event rather than a trend"
        )

    volume = float(row.get("quote_volume_24h") or 0.0)
    if volume < config.min_quote_volume_24h:
        floor = config.min_quote_volume_24h / 1e6
        return f"24h volume ${volume / 1e6:.1f}M below the ${floor:.0f}M floor"

    spread = row.get("spread_pct")
    if spread is not None and spread > config.max_spread_pct:
        return f"spread {spread:.3f}% above the {config.max_spread_pct}% limit"

    onboard = row.get("onboard_date")
    if min_age_ms and onboard:
        try:
            age_ms = now_ms - int(onboard)
            if age_ms < min_age_ms:
                days = age_ms / 86_400_000
                return (
                    f"listed {days:.0f} days ago, under the "
                    f"{config.min_listing_age_days} day minimum"
                )
        except (TypeError, ValueError):
            pass
    return None


# ---------------------------------------------------------------------------
# Applying a rotation
# ---------------------------------------------------------------------------
def _symbols_with_open_positions(db: Session) -> set[str]:
    from app.core.constants import PositionStatus

    rows = (
        db.execute(
            select(Position.symbol).where(
                Position.status.in_([PositionStatus.OPEN.value, PositionStatus.CLOSING.value])
            )
        )
        .scalars()
        .all()
    )
    return {symbol.upper() for symbol in rows}


def _recently_removed(db: Session, config: RotationConfig) -> set[str]:
    """Markets dropped inside the cooldown window.

    Without this a coin sitting on the boundary of rank 20 is added and removed
    every hour, paying a round trip in fees each time for no reason.
    """
    if config.cooldown_hours <= 0:
        return set()
    cutoff = utcnow().timestamp() - config.cooldown_hours * 3600
    runs = db.execute(select(RotationRun).order_by(RotationRun.id.desc()).limit(50)).scalars().all()
    recent: set[str] = set()
    for run in runs:
        if run.ran_at.timestamp() < cutoff:
            break
        recent.update(symbol.upper() for symbol in (run.removed or []))
    return recent


def plan_rotation(
    db: Session, rows: list[dict[str, Any]], config: RotationConfig
) -> dict[str, Any]:
    """Decide the next enabled set without changing anything."""
    accepted, rejected = rank_candidates(rows, config)
    open_positions = _symbols_with_open_positions(db)
    cooling = _recently_removed(db, config) - open_positions

    wanted: list[str] = []
    for candidate in accepted:
        symbol = candidate["symbol"]
        if symbol in cooling:
            rejected.append(
                {
                    "symbol": symbol,
                    "reason": f"removed within the last {config.cooldown_hours}h, cooling down",
                    "change_24h_pct": candidate["change_24h_pct"],
                    "quote_volume_24h": candidate["quote_volume_24h"],
                }
            )
            continue
        wanted.append(symbol)
        if len(wanted) >= config.top_n:
            break

    trading = settings_service.get_trading_config(db)
    current = [symbol.upper() for symbol in trading.enabled_symbols]
    current_set = set(current)
    wanted_set = set(wanted)

    added = [symbol for symbol in wanted if symbol not in current_set]
    removed = [symbol for symbol in current if symbol not in wanted_set]
    # A market with an open position keeps its slot: disabling it would stop the
    # engine managing the exit while the position is still live.
    held_open = [symbol for symbol in removed if symbol in open_positions]
    removed = [symbol for symbol in removed if symbol not in open_positions]

    # Cap the churn so one volatile hour cannot flush the whole book. The cap
    # applies to REMOVALS only: a removal closes a live position, which is the
    # expensive half. Additions are already bounded by top_n, and throttling
    # them would stop the set ever reaching the configured size - a target of
    # twenty starting from ten would take hours to fill for no benefit.
    if len(removed) > config.max_changes_per_run:
        removed = removed[: config.max_changes_per_run]
        removed_set = set(removed)
        # Re-derive what still has to leave so the final set stays consistent.
        added = [
            symbol
            for symbol in added
            if len(current) - len(removed_set) + added.index(symbol) < config.top_n
        ]

    final = [symbol for symbol in current if symbol not in set(removed)]
    final += [symbol for symbol in added if symbol not in set(final)]

    return {
        "selected": accepted[: config.top_n],
        "rejected": rejected[:80],
        "added": added,
        "removed": removed,
        "held_open": held_open,
        "unchanged": [symbol for symbol in current if symbol in wanted_set],
        "final_symbols": final,
        "candidates_considered": len(accepted),
    }


async def run_rotation(
    context: Any,
    db: Session,
    *,
    triggered_by: str = "schedule",
    force_dry_run: bool | None = None,
) -> RotationRun:
    """Rank, plan and (unless it is a dry run) apply the new enabled set."""
    from app.services import event_service, universe_service

    started = time.monotonic()
    config = get_config(db)
    dry_run = config.dry_run if force_dry_run is None else force_dry_run

    record = RotationRun(ran_at=utcnow(), dry_run=dry_run, triggered_by=triggered_by)
    try:
        snapshot = await universe_service.load_universe(context, with_context=False)
        plan = plan_rotation(db, snapshot["rows"], config)

        record.selected = plan["selected"]
        record.rejected = plan["rejected"]
        record.added = plan["added"]
        record.removed = plan["removed"]
        record.held_open = plan["held_open"]
        record.unchanged = plan["unchanged"]
        record.candidates_considered = plan["candidates_considered"]
        record.enabled_after = len(plan["final_symbols"])

        if not dry_run and (plan["added"] or plan["removed"]):
            trading = settings_service.get_trading_config(db)
            before = list(trading.enabled_symbols)
            trading.enabled_symbols = plan["final_symbols"]
            settings_service.save_trading_config(db, trading)
            event_service.audit(
                db,
                action="rotate_enabled_symbols",
                entity="trading_config",
                before={"enabled_symbols": before},
                after={"enabled_symbols": plan["final_symbols"]},
            )
            await context.rebuild(db)

        record.duration_seconds = time.monotonic() - started
        db.add(record)
        db.commit()
        db.refresh(record)

        logger.info(
            "Rotation finished",
            extra={
                "dry_run": dry_run,
                "added": len(record.added or []),
                "removed": len(record.removed or []),
                "held_open": len(record.held_open or []),
            },
        )
        event_service.log_event(
            db,
            message=(
                f"Rotation {'(dry run) ' if dry_run else ''}"
                f"+{len(record.added or [])} -{len(record.removed or [])} markets"
            ),
            category="rotation",
            details={
                "added": record.added,
                "removed": record.removed,
                "held_open": record.held_open,
            },
        )
        return record
    except Exception as exc:
        logger.exception("Rotation failed")
        record.error_message = str(exc)[:1000]
        record.duration_seconds = time.monotonic() - started
        db.add(record)
        db.commit()
        return record


def history(db: Session, limit: int = 30) -> list[RotationRun]:
    return list(
        db.execute(select(RotationRun).order_by(RotationRun.id.desc()).limit(limit)).scalars().all()
    )


def run_to_dict(record: RotationRun) -> dict[str, Any]:
    return {
        "id": record.id,
        "ran_at": record.ran_at,
        "dry_run": record.dry_run,
        "triggered_by": record.triggered_by,
        "selected": record.selected or [],
        "added": record.added or [],
        "removed": record.removed or [],
        "unchanged": record.unchanged or [],
        "held_open": record.held_open or [],
        "rejected": record.rejected or [],
        "candidates_considered": record.candidates_considered,
        "enabled_after": record.enabled_after,
        "duration_seconds": record.duration_seconds,
        "error_message": record.error_message,
    }
