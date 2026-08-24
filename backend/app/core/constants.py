"""Domain enumerations shared by every layer of the platform.

Keeping all enums in one place avoids "magic strings" spread across modules and
makes it impossible for the strategy layer and the execution layer to disagree
about what LONG means.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String enum that serialises cleanly through Pydantic / JSON / SQL."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


# ---------------------------------------------------------------------------
# Trading modes
# ---------------------------------------------------------------------------
class TradingMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class RiskLevel(StrEnum):
    """How aggressive a strategy is, shown to the user before enabling it."""

    SAFE = "safe"
    MEDIUM = "medium"
    RISKY = "risky"


RISK_LEVEL_ORDER: dict[str, int] = {"safe": 0, "medium": 1, "risky": 2}


class MarketType(StrEnum):
    SPOT = "spot"
    FUTURES = "futures"


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------
class SignalType(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


class SignalStatus(StrEnum):
    GENERATED = "generated"
    ACCEPTED = "accepted"
    REJECTED_BY_RISK = "rejected_by_risk"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Orders / positions
# ---------------------------------------------------------------------------
class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


TERMINAL_ORDER_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
)


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ExitReason(StrEnum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    SIGNAL_REVERSAL = "signal_reversal"
    SIGNAL_EXIT = "signal_exit"
    MANUAL = "manual"
    EMERGENCY_STOP = "emergency_stop"
    DAILY_LIMIT = "daily_limit"
    LIQUIDATION = "liquidation"
    END_OF_BACKTEST = "end_of_backtest"


# ---------------------------------------------------------------------------
# Market regime
# ---------------------------------------------------------------------------
class MarketRegime(StrEnum):
    """Primary regime label handed to the strategies."""

    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"
    UNKNOWN = "UNKNOWN"


class TrendRegime(StrEnum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    UNKNOWN = "UNKNOWN"


class VolatilityRegime(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Bot / system state
# ---------------------------------------------------------------------------
class BotStatus(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"


class EmergencyStopLevel(StrEnum):
    """Three escalating levels, exposed as three dashboard buttons."""

    NONE = "NONE"
    HALT_NEW_ENTRIES = "HALT_NEW_ENTRIES"
    CLOSE_ALL_POSITIONS = "CLOSE_ALL_POSITIONS"
    FULL_STOP = "FULL_STOP"


class HealthStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class ConnectionStatus(StrEnum):
    CONNECTED = "CONNECTED"
    CONNECTING = "CONNECTING"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"


class ReconciliationStatus(StrEnum):
    IN_SYNC = "IN_SYNC"
    MISMATCH = "MISMATCH"
    NEVER_RUN = "NEVER_RUN"
    ERROR = "ERROR"


class EventSeverity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class BacktestStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DatasetSplit(StrEnum):
    """Guards against optimising on data that is meant to validate."""

    IN_SAMPLE = "IN_SAMPLE"
    VALIDATION = "VALIDATION"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    FULL = "FULL"


# ---------------------------------------------------------------------------
# Risk rejection codes (stable identifiers used by API, UI and tests)
# ---------------------------------------------------------------------------
class RiskRejectionCode(StrEnum):
    EMERGENCY_STOP = "EMERGENCY_STOP"
    TRADING_DISABLED = "TRADING_DISABLED"
    LIVE_TRADING_NOT_ENABLED = "LIVE_TRADING_NOT_ENABLED"
    SYMBOL_DISABLED = "SYMBOL_DISABLED"
    STRATEGY_DISABLED = "STRATEGY_DISABLED"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    DAILY_LOSS_LIMIT_REACHED = "DAILY_LOSS_LIMIT_REACHED"
    DAILY_PROFIT_TARGET_REACHED = "DAILY_PROFIT_TARGET_REACHED"
    MAX_TRADES_PER_DAY = "MAX_TRADES_PER_DAY"
    MAX_CONSECUTIVE_LOSSES = "MAX_CONSECUTIVE_LOSSES"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    MAX_CONCURRENT_POSITIONS = "MAX_CONCURRENT_POSITIONS"
    POSITION_ALREADY_OPEN = "POSITION_ALREADY_OPEN"
    MAX_DRAWDOWN_REACHED = "MAX_DRAWDOWN_REACHED"
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INVALID_STOP_LOSS = "INVALID_STOP_LOSS"
    POSITION_SIZE_TOO_SMALL = "POSITION_SIZE_TOO_SMALL"
    MIN_NOTIONAL_NOT_MET = "MIN_NOTIONAL_NOT_MET"
    MAX_EXPOSURE_EXCEEDED = "MAX_EXPOSURE_EXCEEDED"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    LEVERAGE_TOO_HIGH = "LEVERAGE_TOO_HIGH"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# ---------------------------------------------------------------------------
# Timeframes
# ---------------------------------------------------------------------------
TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
    "3d": 4320,
    "1w": 10080,
}

SUPPORTED_TIMEFRAMES: tuple[str, ...] = tuple(TIMEFRAME_MINUTES.keys())


def timeframe_to_minutes(timeframe: str) -> int:
    """Return the number of minutes in one candle of the given timeframe."""
    try:
        return TIMEFRAME_MINUTES[timeframe]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported timeframe: {timeframe!r}") from exc


def timeframe_to_ms(timeframe: str) -> int:
    """Return the length of one candle of the given timeframe in milliseconds."""
    return timeframe_to_minutes(timeframe) * 60_000
