"""Runtime settings stored in the database and editable from the dashboard.

Environment variables provide the *defaults*; anything the user changes in the
UI is persisted here so it survives a restart.

Secrets never live in this table.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import MarketType, TradingMode
from app.core.logging import get_logger
from app.models.system import AppSetting
from app.risk.config import RiskConfig
from app.strategies.registry import available_keys

logger = get_logger(__name__)

RISK_CONFIG_KEY = "risk_config"
TRADING_CONFIG_KEY = "trading_config"
NOTIFICATION_CONFIG_KEY = "notification_config"


class TradingConfig(BaseModel):
    """Which markets, strategies and mode the engine should run."""

    mode: TradingMode = TradingMode.PAPER
    market_type: MarketType = MarketType.FUTURES
    timeframe: str = "15m"
    higher_timeframe: str = "4h"
    leverage: int = Field(default=2, ge=1, le=125)
    enabled_symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    enabled_strategies: dict[str, bool] = Field(default_factory=dict)
    auto_start_engine: bool = True

    def is_symbol_enabled(self, symbol: str) -> bool:
        return symbol.upper() in {s.upper() for s in self.enabled_symbols}

    def is_strategy_enabled(self, key: str) -> bool:
        return bool(self.enabled_strategies.get(key, True))


class NotificationConfig(BaseModel):
    """Local, in-dashboard notification preferences."""

    notify_on_signal: bool = True
    notify_on_order: bool = True
    notify_on_risk_rejection: bool = False
    notify_on_daily_target: bool = True
    notify_on_error: bool = True


# ---------------------------------------------------------------------------
# Generic key/value helpers
# ---------------------------------------------------------------------------
def get_json_setting(db: Session, key: str, default: dict | None = None) -> dict:
    """Read a JSON settings blob."""
    row = db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict):
        return copy.deepcopy(default) if default is not None else {}
    return copy.deepcopy(row.value)


def set_json_setting(db: Session, key: str, value: dict, description: str = "") -> dict:
    """Create or update a JSON settings blob."""
    row = db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()
    if row is None:
        row = AppSetting(key=key, value=value, description=description)
        db.add(row)
    else:
        row.value = value
        if description:
            row.description = description
    db.commit()
    return copy.deepcopy(value)


# ---------------------------------------------------------------------------
# Risk configuration
# ---------------------------------------------------------------------------
def get_risk_config(db: Session) -> RiskConfig:
    """Effective risk configuration (database first, environment as fallback)."""
    stored = get_json_setting(db, RISK_CONFIG_KEY, {})
    if not stored:
        config = RiskConfig.from_settings()
        set_json_setting(db, RISK_CONFIG_KEY, config.model_dump(), "Risk limits")
        return config
    try:
        return RiskConfig(**stored)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Stored risk config is invalid, using defaults", extra={"error": str(exc)})
        return RiskConfig.from_settings()


def save_risk_config(db: Session, config: RiskConfig) -> RiskConfig:
    """Persist a validated risk configuration."""
    set_json_setting(db, RISK_CONFIG_KEY, config.model_dump(), "Risk limits")
    logger.info("Risk configuration updated", extra={"config": config.model_dump()})
    return config


# ---------------------------------------------------------------------------
# Trading configuration
# ---------------------------------------------------------------------------
def default_trading_config() -> TradingConfig:
    """Safe defaults: paper trading, both markets on, every strategy available."""
    settings = get_settings()
    return TradingConfig(
        mode=TradingMode.PAPER,
        market_type=settings.binance_market_type,
        timeframe=settings.default_timeframe,
        higher_timeframe=settings.higher_timeframe,
        leverage=min(2, settings.max_leverage),
        enabled_symbols=settings.enabled_symbol_list,
        enabled_strategies={key: True for key in available_keys()},
    )


def get_trading_config(db: Session) -> TradingConfig:
    """Effective trading configuration."""
    stored = get_json_setting(db, TRADING_CONFIG_KEY, {})
    if not stored:
        config = default_trading_config()
        set_json_setting(db, TRADING_CONFIG_KEY, config.model_dump(mode="json"), "Trading setup")
        return config
    try:
        config = TradingConfig(**stored)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Stored trading config invalid, using defaults", extra={"error": str(exc)})
        return default_trading_config()
    for key in available_keys():
        config.enabled_strategies.setdefault(key, True)
    return config


def save_trading_config(db: Session, config: TradingConfig) -> TradingConfig:
    """Persist the trading configuration.

    Note: switching the mode to live still requires the separate two-step
    confirmation handled by the bot service.
    """
    set_json_setting(db, TRADING_CONFIG_KEY, config.model_dump(mode="json"), "Trading setup")
    logger.info("Trading configuration updated", extra={"mode": config.mode.value})
    return config


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def get_notification_config(db: Session) -> NotificationConfig:
    stored = get_json_setting(db, NOTIFICATION_CONFIG_KEY, {})
    try:
        return NotificationConfig(**stored) if stored else NotificationConfig()
    except Exception:  # pragma: no cover - defensive
        return NotificationConfig()


def save_notification_config(db: Session, config: NotificationConfig) -> NotificationConfig:
    set_json_setting(db, NOTIFICATION_CONFIG_KEY, config.model_dump(), "Notifications")
    return config


def all_settings(db: Session) -> dict[str, Any]:
    """Everything the settings page needs in one call."""
    return {
        "risk": get_risk_config(db).model_dump(),
        "trading": get_trading_config(db).model_dump(mode="json"),
        "notifications": get_notification_config(db).model_dump(),
    }
