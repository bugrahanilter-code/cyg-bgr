"""Database bootstrap: schema creation and seed data."""

from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.database.base import Base
from app.database.session import SessionLocal, engine
from app.exchange.filters import default_filters_for
from app.models import Symbol
from app.models.trading import StrategyRecord
from app.services import settings_service
from app.services.bot_state_service import get_state
from app.strategies.registry import strategy_metadata

logger = get_logger(__name__)


def create_tables() -> None:
    """Create any missing table.

    Alembic owns the schema in production; this keeps local development and
    the test suite friction free.
    """
    Base.metadata.create_all(bind=engine)
    tables = inspect(engine).get_table_names()
    logger.info("Database schema ready", extra={"tables": len(tables)})


def seed_symbols(db: Session) -> None:
    """Insert the markets from the configuration if they do not exist yet."""
    settings = get_settings()
    enabled = set(settings.enabled_symbol_list)
    for symbol in settings.available_symbol_list:
        existing = db.execute(select(Symbol).where(Symbol.symbol == symbol)).scalar_one_or_none()
        if existing is not None:
            continue
        base, _, quote = symbol.partition("/")
        filters = default_filters_for(symbol)
        db.add(
            Symbol(
                symbol=symbol,
                base_asset=base,
                quote_asset=quote or settings.quote_currency,
                market_type=settings.binance_market_type.value,
                enabled=symbol in enabled,
                tick_size=filters.tick_size,
                step_size=filters.step_size,
                min_quantity=filters.min_quantity,
                min_notional=filters.min_notional,
                price_precision=filters.price_precision,
                quantity_precision=filters.quantity_precision,
                max_leverage=filters.max_leverage,
                maintenance_margin_rate=filters.maintenance_margin_rate,
            )
        )
    db.commit()


def seed_strategies(db: Session) -> None:
    """Register every strategy implementation in the database."""
    for meta in strategy_metadata():
        existing = db.execute(
            select(StrategyRecord).where(StrategyRecord.key == meta["key"])
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                StrategyRecord(
                    key=meta["key"],
                    name=meta["name"],
                    family=meta["family"],
                    description=meta["description"],
                    enabled=True,
                )
            )
        else:
            existing.name = meta["name"]
            existing.family = meta["family"]
            existing.description = meta["description"]
    db.commit()


def seed_reference_markets(db: Session) -> int:
    """Make gold and the FX majors available without a manual import.

    They are inserted as *available*, never as *enabled*: EUR/USD and USD/JPY
    cannot be traded at all, and the Risk Engine rejects any signal on them.
    They exist so a crypto result can be compared against a market with six
    times less friction.
    """
    from app.market_data import reference_markets

    added = 0
    for market in reference_markets.REFERENCE_MARKETS.values():
        existing = db.execute(
            select(Symbol).where(Symbol.symbol == market.symbol)
        ).scalar_one_or_none()
        if existing is not None:
            continue
        base, _, quote = market.symbol.partition("/")
        filters = default_filters_for(market.symbol)
        db.add(
            Symbol(
                symbol=market.symbol,
                base_asset=base,
                quote_asset=quote,
                enabled=False,
                tick_size=filters.tick_size,
                step_size=filters.step_size,
                min_quantity=filters.min_quantity,
                min_notional=filters.min_notional,
                price_precision=filters.price_precision,
                quantity_precision=filters.quantity_precision,
                max_leverage=filters.max_leverage,
            )
        )
        added += 1
    if added:
        db.commit()
        logger.info("Reference markets seeded", extra={"added": added})
    return added


def seed_settings(db: Session) -> None:
    """Materialise the conservative default configuration."""
    settings_service.get_risk_config(db)
    settings_service.get_trading_config(db)
    get_state(db)


def recover_orphaned_sweeps(db: Session) -> int:
    """Close matrix backtests that were interrupted by a restart.

    A sweep lives in a background task, so a process restart kills it while the
    row still says RUNNING. Leaving it that way would show a phantom job making
    no progress forever, so the interruption is recorded instead.
    """
    from app.core.constants import BacktestStatus
    from app.models.sweep import BacktestSweep

    orphans = (
        db.execute(
            select(BacktestSweep).where(BacktestSweep.status == BacktestStatus.RUNNING.value)
        )
        .scalars()
        .all()
    )
    for sweep in orphans:
        sweep.status = BacktestStatus.FAILED.value
        sweep.error_message = (
            "Interrupted by an application restart. Completed cells were kept; "
            "start a new sweep to finish the grid."
        )
        sweep.current_task = ""
        sweep.completed_at = utcnow()
    if orphans:
        db.commit()
        logger.warning("Interrupted sweeps closed", extra={"count": len(orphans)})
    return len(orphans)


def init_database(create: bool = True) -> None:
    """Full bootstrap used by the application startup and by the tests."""
    if create:
        create_tables()
    with SessionLocal() as db:
        seed_symbols(db)
        seed_strategies(db)
        seed_settings(db)
        seed_reference_markets(db)
        recover_orphaned_sweeps(db)
    logger.info("Database bootstrap complete")


if __name__ == "__main__":  # pragma: no cover - manual helper
    init_database()
