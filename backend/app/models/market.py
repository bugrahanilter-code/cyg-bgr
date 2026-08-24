"""Market reference data: tradable symbols and OHLCV candles."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MarketType
from app.core.time_utils import utcnow
from app.database.base import Amount, Base, TimestampMixin


class Symbol(TimestampMixin, Base):
    """A tradable market plus the exchange filters required to size orders.

    Symbols are data, never hard-coded constants: adding a new coin is an INSERT
    (or a dashboard toggle), not a code change.
    """

    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    base_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    market_type: Mapped[str] = mapped_column(String(16), default=MarketType.FUTURES.value)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Exchange filters (refreshed from the exchange when credentials exist).
    price_precision: Mapped[int] = mapped_column(Integer, default=2)
    quantity_precision: Mapped[int] = mapped_column(Integer, default=3)
    tick_size: Mapped[float] = mapped_column(Amount, default=0.01)
    step_size: Mapped[float] = mapped_column(Amount, default=0.001)
    min_quantity: Mapped[float] = mapped_column(Amount, default=0.001)
    min_notional: Mapped[float] = mapped_column(Amount, default=5.0)
    max_leverage: Mapped[int] = mapped_column(Integer, default=20)
    maintenance_margin_rate: Mapped[float] = mapped_column(Amount, default=0.005)
    filters_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Symbol {self.symbol} enabled={self.enabled}>"


class Candle(TimestampMixin, Base):
    """A single OHLCV candle.

    open_time is stored as exchange milliseconds so there is never any timezone
    ambiguity when comparing local data with exchange data.
    """

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle_symbol_tf_open"),
        Index("ix_candles_lookup", "symbol", "timeframe", "open_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    close_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    open: Mapped[float] = mapped_column(Amount, nullable=False)
    high: Mapped[float] = mapped_column(Amount, nullable=False)
    low: Mapped[float] = mapped_column(Amount, nullable=False)
    close: Mapped[float] = mapped_column(Amount, nullable=False)
    volume: Mapped[float] = mapped_column(Amount, nullable=False, default=0.0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Candle {self.symbol} {self.timeframe} {self.open_time} c={self.close}>"
