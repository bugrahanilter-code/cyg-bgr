"""The full tradable universe: every Binance market plus its 24 hour context.

Two sources are merged here:

* **Binance** (authoritative) — which markets exist, last price, 24h OHLC,
  volume, live bid/ask spread, leverage caps.
* **TradingView** (optional decoration) — technical rating, RSI, ATR, relative
  volume. If it is unreachable the browser simply shows Binance data.

Nothing in this module feeds a trading decision. It exists so a human can look
at 500+ markets and decide which handful to enable.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.exchange.filters import default_filters_for
from app.market_data import reference_markets
from app.market_data.providers.tradingview import TradingViewProvider, to_tradingview_symbol
from app.models.market import Symbol

logger = get_logger(__name__)

#: Screener data is refreshed at most this often.
CACHE_TTL_SECONDS = 45.0

_tradingview = TradingViewProvider()

_cache: dict[str, Any] = {"rows": [], "fetched_at": 0.0, "sources": {}}
_lock = asyncio.Lock()


async def load_universe(
    context: Any,
    *,
    force: bool = False,
    include_non_crypto: bool = False,
    with_context: bool = True,
) -> dict[str, Any]:
    """Return every market with merged statistics.

    The result is cached briefly because the market browser polls it and a full
    refresh means one ``fetch_tickers`` call plus a handful of screener pages.
    """
    async with _lock:
        now = time.monotonic()
        age = now - float(_cache["fetched_at"])
        if not force and _cache["rows"] and age < CACHE_TTL_SECONDS:
            return _snapshot(age)

        gateway = context.data_gateway
        if gateway is None:
            raise RuntimeError("The exchange gateway is not ready yet")

        quote = context.settings.quote_currency
        exchange_rows = await gateway.fetch_market_universe(
            quote=quote,
            include_non_crypto=include_non_crypto,
            always_include=set(reference_markets.REFERENCE_MARKETS),
        )

        sources: dict[str, Any] = {
            "binance": {"ok": True, "markets": len(exchange_rows), "error": None}
        }

        tv_context: dict[str, Any] = {}
        if with_context:
            stats = await _tradingview.fetch_context()
            tv_context = {key: value.to_dict() for key, value in stats.items()}
            sources["tradingview"] = {
                "ok": bool(tv_context),
                "markets": len(tv_context),
                "error": _tradingview.last_error,
            }

        market_type = context.settings.binance_market_type.value
        settings = context.settings
        for row in exchange_rows:
            extra = tv_context.get(row["symbol"]) or {}
            row["tv_symbol"] = extra.get(
                "tv_symbol", to_tradingview_symbol(row["symbol"], market_type)
            )
            row["tv_rating"] = extra.get("tv_rating")
            row["tv_rating_label"] = extra.get("tv_rating_label", "UNKNOWN")
            row["tv_rsi"] = extra.get("tv_rsi")
            row["tv_atr"] = extra.get("tv_atr")
            row["tv_relative_volume"] = extra.get("tv_relative_volume")
            row["tv_volatility_daily_pct"] = extra.get("tv_volatility_daily_pct")
            # ATR as a percentage of price is the number a position sizer cares
            # about; the absolute ATR of a $78k coin and a $0.09 coin are not
            # comparable.
            atr = extra.get("tv_atr")
            price = row.get("last_price") or 0.0
            row["atr_pct"] = (atr / price * 100.0) if atr and price else None

            # The number that decides whether a market is worth trading at all:
            # what one open-and-close costs before the strategy earns anything.
            # Taker fee twice, slippage twice, plus the live spread once.
            spread = row.get("spread_pct") or 0.0
            row["round_trip_cost_pct"] = (
                2 * settings.taker_fee_pct + 2 * settings.slippage_pct + spread
            )

            _annotate_kind(row)

        # EUR/USD and USD/JPY have no Binance market, so they are appended
        # rather than filtered out of the exchange listing.
        exchange_rows.extend(reference_market_rows())
        exchange_rows.sort(key=lambda item: item["quote_volume_24h"], reverse=True)
        for rank, item in enumerate(exchange_rows, start=1):
            item["volume_rank"] = rank

        _cache["rows"] = exchange_rows
        _cache["fetched_at"] = now
        _cache["sources"] = sources
        logger.info(
            "Market universe refreshed",
            extra={"markets": len(exchange_rows), "with_context": len(tv_context)},
        )
        return _snapshot(0.0)


def _snapshot(age_seconds: float) -> dict[str, Any]:
    return {
        "rows": list(_cache["rows"]),
        "sources": dict(_cache["sources"]),
        "age_seconds": round(age_seconds, 1),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }


def invalidate() -> None:
    """Drop the cache so the next read hits the exchange."""
    _cache["fetched_at"] = 0.0


async def sync_all_symbols(
    context: Any,
    db: Session,
    *,
    limit: int | None = None,
    min_quote_volume: float = 0.0,
    include_non_crypto: bool = False,
) -> dict[str, Any]:
    """Insert every market of the exchange into the ``symbols`` table.

    Symbols are stored as *available*, never as *enabled*. Enabling a market is
    always a deliberate decision the user makes, because each enabled market
    multiplies the number of strategy evaluations per candle and the number of
    positions the risk engine may have to supervise at once.

    ``limit`` and ``min_quote_volume`` exist because a dead market with $2k of
    daily turnover cannot absorb a real order and only adds noise to the list.
    """
    snapshot = await load_universe(
        context, force=True, include_non_crypto=include_non_crypto, with_context=False
    )
    rows: list[dict[str, Any]] = snapshot["rows"]

    # Reference markets are never filtered out by volume or by the top-N limit:
    # they are there on purpose, and EUR/USD has no exchange volume to rank by.
    pinned = [row for row in rows if row.get("reference")]
    rest = [row for row in rows if not row.get("reference")]
    if min_quote_volume > 0:
        rest = [row for row in rest if row["quote_volume_24h"] >= min_quote_volume]
    if limit:
        rest = rest[:limit]
    rows = pinned + rest

    existing = {row.symbol: row for row in db.execute(select(Symbol)).scalars().all()}

    gateway = context.data_gateway
    market_type = context.settings.binance_market_type.value
    added: list[str] = []
    updated: list[str] = []

    for entry in rows:
        symbol = entry["symbol"]
        if reference_markets.get(symbol) and not reference_markets.is_tradable(symbol):
            # Binance has no market for these, so asking it for trading rules is
            # a guaranteed round trip to a failure. They cannot be ordered
            # anyway, so placeholder filters are honest here.
            filters = default_filters_for(symbol)
        else:
            try:
                filters = await gateway.fetch_symbol_filters(symbol)
            except Exception:
                filters = default_filters_for(symbol)

        record = existing.get(symbol)
        if record is None:
            record = Symbol(
                symbol=symbol,
                base_asset=entry["base_asset"],
                quote_asset=entry["quote_asset"],
                market_type=market_type,
                enabled=False,
            )
            db.add(record)
            added.append(symbol)
        else:
            updated.append(symbol)

        record.tick_size = filters.tick_size
        record.step_size = filters.step_size
        record.min_quantity = filters.min_quantity
        record.min_notional = filters.min_notional
        record.price_precision = filters.price_precision
        record.quantity_precision = filters.quantity_precision
        record.max_leverage = filters.max_leverage
        record.filters_synced_at = utcnow()
        context.filters[symbol] = filters

    db.commit()
    if context.engine is not None:
        context.engine.filters = context.filters

    invalidate()
    logger.info(
        "Full market universe synchronised",
        extra={"added": len(added), "updated": len(updated)},
    )
    return {
        "added": added,
        "updated": updated,
        "total_available": len(existing) + len(added),
        "skipped_low_volume": (
            len(snapshot["rows"]) - len(rows) if min_quote_volume > 0 or limit else 0
        ),
    }


def stored_symbols(db: Session) -> list[str]:
    """Every symbol currently known to the database, cheapest possible query."""
    return list(db.execute(select(Symbol.symbol).order_by(Symbol.symbol)).scalars().all())


def _annotate_kind(row: dict[str, Any]) -> None:
    """Tag a market row with its kind, whether it is tradable and its session.

    Ordinary crypto perpetuals get the defaults. The handful of reference
    markets carry the extra warnings a human needs before backtesting them:
    a weekend close, a short listing history, or the fact that no order can
    ever be filled on them.
    """
    market = reference_markets.get(row["symbol"])
    if market is None:
        row["kind"] = reference_markets.MarketKind.CRYPTO.value
        row["tradable"] = True
        row["reference"] = False
        row["session"] = "24/7"
        row["history_source"] = "binance"
        row["notes"] = ""
        return

    row["kind"] = market.kind.value
    row["tradable"] = market.tradable
    row["reference"] = True
    row["session"] = market.session
    row["history_source"] = market.provider
    row["notes"] = market.notes


def reference_market_rows() -> list[dict[str, Any]]:
    """Rows for reference markets that Binance does not list at all.

    EUR/USD and USD/JPY have no Binance market, so they never appear in the
    exchange universe and have to be added here. Their price fields stay empty
    until candles are downloaded: there is no live ticker for them.
    """
    rows: list[dict[str, Any]] = []
    for market in reference_markets.externally_sourced().values():
        base, _, quote = market.symbol.partition("/")
        row: dict[str, Any] = {
            "symbol": market.symbol,
            "base_asset": base,
            "quote_asset": quote,
            "is_crypto": False,
            "last_price": 0.0,
            "open_24h": 0.0,
            "high_24h": 0.0,
            "low_24h": 0.0,
            "change_24h_pct": 0.0,
            "change_24h_abs": 0.0,
            "base_volume_24h": 0.0,
            "quote_volume_24h": 0.0,
            "weighted_average": 0.0,
            "trade_count_24h": 0,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "range_position_pct": None,
            "maint_margin_pct": None,
            "onboard_date": None,
            "volume_rank": 0,
            "tv_symbol": "",
            "tv_rating": None,
            "tv_rating_label": "UNKNOWN",
            "tv_rsi": None,
            "tv_atr": None,
            "tv_relative_volume": None,
            "tv_volatility_daily_pct": None,
            "atr_pct": None,
            "round_trip_cost_pct": market.typical_round_trip_cost_pct,
        }
        _annotate_kind(row)
        rows.append(row)
    return rows
