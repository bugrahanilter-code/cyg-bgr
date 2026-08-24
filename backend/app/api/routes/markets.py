"""The market browser: every coin on the exchange with its 24 hour context."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import Context, DbSession
from app.core.constants import SUPPORTED_TIMEFRAMES
from app.core.time_utils import from_ms
from app.market_data import reference_markets
from app.models.market import Candle, Symbol
from app.schemas.common import MessageResponse
from app.services import event_service, settings_service, universe_service

router = APIRouter(prefix="/markets", tags=["markets"])

SORTABLE = {
    "quote_volume_24h",
    "change_24h_pct",
    "last_price",
    "symbol",
    "spread_pct",
    "tv_rating",
    "atr_pct",
    "range_position_pct",
}


class EnableRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    enabled: bool = True
    #: Replace the enabled set instead of adding to it.
    replace: bool = False


class SyncRequest(BaseModel):
    limit: int | None = None
    min_quote_volume: float = 0.0
    include_non_crypto: bool = False


@router.get("/universe", summary="Every market with 24 hour statistics")
async def universe(
    db: DbSession,
    context: Context,
    search: str = "",
    sort: str = "quote_volume_24h",
    descending: bool = True,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    min_quote_volume: float = 0.0,
    only_enabled: bool = False,
    include_non_crypto: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """Paginated, searchable, sortable view of the whole exchange."""
    try:
        snapshot = await universe_service.load_universe(
            context, force=refresh, include_non_crypto=include_non_crypto
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Binance: {exc}") from exc

    # The single source of truth for "traded" is the trading config, not the
    # symbols table: the symbols table records what *exists*, the trading config
    # records what the user has switched on.
    trading = settings_service.get_trading_config(db)
    enabled = {symbol.upper() for symbol in trading.enabled_symbols}
    known = set(universe_service.stored_symbols(db))

    rows: list[dict[str, Any]] = []
    needle = search.strip().upper()
    for row in snapshot["rows"]:
        if needle and needle not in row["symbol"] and needle not in row["base_asset"]:
            continue
        if row["quote_volume_24h"] < min_quote_volume:
            continue
        item = dict(row)
        item["enabled"] = row["symbol"] in enabled
        item["in_database"] = row["symbol"] in known
        if only_enabled and not item["enabled"]:
            continue
        rows.append(item)

    key = sort if sort in SORTABLE else "quote_volume_24h"

    def sort_key(item: dict[str, Any]) -> tuple[bool, Any]:
        value = item.get(key)
        # Markets with no value for the chosen column sort last either way,
        # rather than being treated as zero and floating to the top.
        return (value is None, value if key == "symbol" else (value or 0.0))

    rows.sort(key=sort_key, reverse=descending)

    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "rows": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "enabled_count": len(enabled),
        "known_count": len(known),
        "sources": snapshot["sources"],
        "age_seconds": snapshot["age_seconds"],
        "sortable_fields": sorted(SORTABLE),
        "note": (
            "24 hour figures come from Binance. Technical rating, RSI and ATR come "
            "from the TradingView screener and are context only: no trading decision "
            "in this platform reads them."
        ),
    }


@router.get("/detail", summary="One market in detail")
async def detail(db: DbSession, context: Context, symbol: str) -> dict[str, Any]:
    target = symbol.upper()
    snapshot = await universe_service.load_universe(context)
    row = next((item for item in snapshot["rows"] if item["symbol"] == target), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{target} is not an available market")

    record = db.execute(select(Symbol).where(Symbol.symbol == target)).scalar_one_or_none()
    trading = settings_service.get_trading_config(db)
    reference = reference_markets.get(target)
    regime = None
    if context.engine is not None:
        current = context.engine.latest_regime(target)
        regime = current.to_dict() if current else None

    return {
        "market": row,
        "enabled": trading.is_symbol_enabled(target),
        "in_database": record is not None,
        "filters": (
            {
                "tick_size": record.tick_size,
                "step_size": record.step_size,
                "min_quantity": record.min_quantity,
                "min_notional": record.min_notional,
                "max_leverage": record.max_leverage,
                "synced_at": record.filters_synced_at,
            }
            if record
            else None
        ),
        "regime": regime,
        "reference": (
            {
                "kind": reference.kind.value,
                "description": reference.description,
                "session": reference.session,
                "tradable": reference.tradable,
                "history_source": reference.provider,
                "history_limits": reference.history_limits,
                "has_volume": reference.has_volume,
                "typical_round_trip_cost_pct": reference.typical_round_trip_cost_pct,
                "notes": reference.notes,
                "untestable_strategies": list(reference_markets.untestable_strategies(target)),
            }
            if reference is not None
            else None
        ),
        "data_coverage": _coverage_for(db, target),
        "live_price": context.market_data.last_price(target) if context.market_data else None,
    }


@router.get("/data-coverage", summary="Which candles are cached locally")
def data_coverage(db: DbSession, symbol: str | None = None) -> dict[str, Any]:
    """Report cached history per market and timeframe.

    The sweep page reads this to show what can be backtested right now without
    waiting for a download.
    """
    query = select(
        Candle.symbol,
        Candle.timeframe,
        func.count(Candle.id),
        func.min(Candle.open_time),
        func.max(Candle.open_time),
    ).group_by(Candle.symbol, Candle.timeframe)
    if symbol:
        query = query.where(Candle.symbol == symbol.upper())

    coverage: dict[str, dict[str, Any]] = {}
    for market, timeframe, count, first_ms, last_ms in db.execute(query).all():
        coverage.setdefault(market, {})[timeframe] = {
            "candles": int(count),
            "from": from_ms(int(first_ms)).isoformat() if first_ms else None,
            "to": from_ms(int(last_ms)).isoformat() if last_ms else None,
        }
    return {
        "coverage": coverage,
        "markets": len(coverage),
        "timeframes": list(SUPPORTED_TIMEFRAMES),
    }


def _coverage_for(db, symbol: str) -> dict[str, Any]:
    """Cached candle count per timeframe for one market."""
    rows = db.execute(
        select(
            Candle.timeframe,
            func.count(Candle.id),
            func.min(Candle.open_time),
            func.max(Candle.open_time),
        )
        .where(Candle.symbol == symbol)
        .group_by(Candle.timeframe)
    ).all()
    return {
        timeframe: {
            "candles": int(count),
            "from": from_ms(int(first_ms)).isoformat() if first_ms else None,
            "to": from_ms(int(last_ms)).isoformat() if last_ms else None,
        }
        for timeframe, count, first_ms, last_ms in rows
    }


@router.post("/sync", summary="Import every Binance market into the database")
async def sync(payload: SyncRequest, db: DbSession, context: Context) -> dict[str, Any]:
    """Add all markets as *available*. Nothing is enabled for trading by this.

    Enabling a market has real consequences (more strategy evaluations per
    candle, more positions the risk engine has to supervise), so it stays a
    separate, deliberate action.
    """
    try:
        result = await universe_service.sync_all_symbols(
            context,
            db,
            limit=payload.limit,
            min_quote_volume=payload.min_quote_volume,
            include_non_crypto=payload.include_non_crypto,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Binance: {exc}") from exc

    event_service.audit(
        db,
        action="sync_all_symbols",
        entity="symbol",
        after={"added": len(result["added"]), "updated": len(result["updated"])},
    )
    result["message"] = (
        f"{len(result['added'])} market(s) added, {len(result['updated'])} refreshed. "
        f"{result['total_available']} markets are now available for backtesting. "
        "None of them were enabled for trading."
    )
    return result


@router.post("/enable", response_model=MessageResponse, summary="Enable markets for trading")
async def enable(payload: EnableRequest, db: DbSession, context: Context) -> MessageResponse:
    """Add or remove markets from the traded set."""
    config = settings_service.get_trading_config(db)
    before = list(config.enabled_symbols)
    wanted = [symbol.upper() for symbol in payload.symbols]

    if payload.replace:
        current = wanted if payload.enabled else []
    else:
        current = list(config.enabled_symbols)
        for symbol in wanted:
            if payload.enabled and symbol not in current:
                current.append(symbol)
            elif not payload.enabled and symbol in current:
                current.remove(symbol)

    if not current:
        raise HTTPException(
            status_code=400,
            detail="At least one market must stay enabled, otherwise the engine has nothing to do.",
        )

    config.enabled_symbols = current
    settings_service.save_trading_config(db, config)
    event_service.audit(
        db,
        action="update_enabled_symbols",
        entity="trading_config",
        before={"enabled_symbols": before},
        after={"enabled_symbols": current},
    )
    await context.rebuild(db)

    warning = ""
    if len(current) > 25:
        warning = (
            f" Warning: {len(current)} enabled markets means {len(current)} strategy "
            "evaluations per candle and up to that many concurrent positions. Check the "
            "risk limits before starting the bot."
        )
    return MessageResponse(
        message=f"{len(current)} market(s) enabled for trading.{warning}",
        details={"enabled_symbols": current},
    )
