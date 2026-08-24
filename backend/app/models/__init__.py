"""SQLAlchemy ORM models.

Importing this package registers every table on Base.metadata, which is what
Alembic and the test bootstrap rely on.
"""

from app.models.account import BalanceSnapshot, DailyStatistic
from app.models.backtest import Backtest, BacktestResult
from app.models.market import Candle, Symbol
from app.models.system import ApiCredential, AppSetting, AuditLog, BotState, SystemEvent
from app.models.trading import (
    Order,
    Position,
    Signal,
    StrategyParameter,
    StrategyRecord,
    Trade,
)

__all__ = [
    "ApiCredential",
    "AppSetting",
    "AuditLog",
    "Backtest",
    "BacktestResult",
    "BalanceSnapshot",
    "BotState",
    "Candle",
    "DailyStatistic",
    "Order",
    "Position",
    "Signal",
    "StrategyParameter",
    "StrategyRecord",
    "Symbol",
    "SystemEvent",
    "Trade",
]
