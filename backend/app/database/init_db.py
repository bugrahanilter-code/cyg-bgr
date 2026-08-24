"""Database bootstrap: schema creation and seed data."""

from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
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


def seed_settings(db: Session) -> None:
    """Materialise the conservative default configuration."""
    settings_service.get_risk_config(db)
    settings_service.get_trading_config(db)
    get_state(db)


def init_database(create: bool = True) -> None:
    """Full bootstrap used by the application startup and by the tests."""
    if create:
        create_tables()
    with SessionLocal() as db:
        seed_symbols(db)
        seed_strategies(db)
        seed_settings(db)
    logger.info("Database bootstrap complete")


if __name__ == "__main__":  # pragma: no cover - manual helper
    init_database()
