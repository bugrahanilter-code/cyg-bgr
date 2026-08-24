"""Request bodies. Every input the API accepts is validated here."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.constants import EmergencyStopLevel, MarketType, TradingMode
from app.risk.config import RiskConfig


class CredentialsRequest(BaseModel):
    """Binance API credentials submitted from the settings page."""

    api_key: str = Field(min_length=8, max_length=256)
    api_secret: str = Field(min_length=8, max_length=256)
    market_type: MarketType = MarketType.FUTURES
    testnet: bool = False
    #: The user must confirm the withdrawal permission is disabled.
    withdrawal_disabled_confirmed: bool = False

    @field_validator("api_key", "api_secret")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class TradingConfigRequest(BaseModel):
    """Editable trading configuration."""

    mode: TradingMode | None = None
    market_type: MarketType | None = None
    timeframe: str | None = None
    higher_timeframe: str | None = None
    leverage: int | None = Field(default=None, ge=1, le=125)
    enabled_symbols: list[str] | None = None
    enabled_strategies: dict[str, bool] | None = None
    auto_start_engine: bool | None = None


class RiskConfigRequest(RiskConfig):
    """Full risk configuration replacement."""


class EmergencyStopRequest(BaseModel):
    """Arm or clear the kill switch."""

    level: EmergencyStopLevel
    reason: str = Field(default="", max_length=500)


class LiveTradingRequest(BaseModel):
    """Two-step live trading confirmation."""

    confirmed: bool
    acknowledge_risk: bool = False
    acknowledge_no_profit_guarantee: bool = False


class StrategyUpdateRequest(BaseModel):
    """Enable/disable a strategy or change its parameters."""

    enabled: bool | None = None
    params: dict[str, Any] | None = None


class ClosePositionRequest(BaseModel):
    reason: str = Field(default="manual", max_length=64)


class BacktestRunRequest(BaseModel):
    """Backtest lab form."""

    strategy_key: str
    symbol: str
    timeframe: str = "15m"
    start: datetime
    end: datetime
    starting_capital: float = Field(default=10_000.0, gt=0)
    leverage: int = Field(default=2, ge=1, le=125)
    params: dict[str, Any] = Field(default_factory=dict)
    taker_fee_pct: float = Field(default=0.04, ge=0.0, le=1.0)
    slippage_pct: float = Field(default=0.02, ge=0.0, le=5.0)
    funding_rate_pct_per_8h: float = Field(default=0.01, ge=-1.0, le=1.0)
    apply_funding: bool = True
    respect_daily_limits: bool = True
    risk: RiskConfig | None = None
    walk_forward: bool = False
    walk_forward_folds: int = Field(default=4, ge=2, le=12)
    param_grid: dict[str, list[Any]] = Field(default_factory=dict)
    name: str = ""


class CandleDownloadRequest(BaseModel):
    symbol: str
    timeframe: str = "15m"
    start: datetime
    end: datetime


class PaperResetRequest(BaseModel):
    starting_balance: float = Field(default=10_000.0, gt=0)
    clear_history: bool = False
