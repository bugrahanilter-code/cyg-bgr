"""Environment configuration.

Only *bootstrap* configuration lives here (things that must be known before the
database is reachable: connection strings, secrets, safety switches).

Everything a user is expected to tune at runtime — risk limits, enabled
symbols, strategy parameters — lives in the database and is editable from the
dashboard. See app.services.settings_service.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import MarketType, TradingMode

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Core ---------------------------------------------------------------
    app_env: str = "development"
    app_name: str = "Crypto Algorithmic Trading Platform"
    api_prefix: str = "/api"
    secret_key: str = ""
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173"
    data_dir: str = str(BACKEND_DIR / "data")

    # -- Database -----------------------------------------------------------
    database_url: str = "postgresql+psycopg2://trader:change_this_password@db:5432/trading"
    db_echo: bool = False
    # When true the tables are created directly from the SQLAlchemy metadata.
    # Alembic remains the source of truth in docker; this is a dev convenience.
    auto_create_tables: bool = True

    # -- Binance ------------------------------------------------------------
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = False
    binance_market_type: MarketType = MarketType.FUTURES
    binance_recv_window: int = 5000
    binance_ws_base: str = "wss://fstream.binance.com/stream"
    binance_ws_base_spot: str = "wss://stream.binance.com:9443/stream"

    # -- Trading ------------------------------------------------------------
    trading_mode: TradingMode = TradingMode.PAPER
    #: Master safety switch. Even when true, the user still has to confirm
    #: live trading from the dashboard (two-step activation).
    live_trading_enabled: bool = False
    enabled_symbols: str = "BTC/USDT,ETH/USDT"
    quote_currency: str = "USDT"
    default_timeframe: str = "15m"
    higher_timeframe: str = "4h"
    paper_starting_balance: float = 10_000.0

    # -- Risk defaults (conservative) --------------------------------------
    risk_per_trade_pct: float = 0.5
    daily_profit_target_pct: float = 2.0
    daily_loss_limit_pct: float = 1.5
    max_concurrent_positions: int = 2
    max_trades_per_day: int = 15
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 30
    max_drawdown_pct: float = 15.0
    max_leverage: int = 3
    max_position_notional_pct: float = 100.0
    max_total_exposure_pct: float = 200.0
    min_signal_confidence: float = 0.35
    max_spread_pct: float = 0.15

    # -- Cost model ---------------------------------------------------------
    taker_fee_pct: float = 0.04
    maker_fee_pct: float = 0.02
    slippage_pct: float = 0.02
    funding_rate_pct_per_8h: float = 0.01

    # -- Engine timings -----------------------------------------------------
    engine_loop_interval_seconds: float = 5.0
    reconciliation_interval_seconds: float = 60.0
    market_data_stale_seconds: float = 120.0
    market_data_poll_seconds: float = 15.0
    heartbeat_interval_seconds: float = 10.0
    #: Set to false in tests / CI so no background task touches the network.
    enable_background_engine: bool = True

    # -- Backtesting --------------------------------------------------------
    backtest_max_candles: int = 200_000

    # -- Misc ---------------------------------------------------------------
    request_timeout_seconds: float = Field(default=20.0, ge=1.0)

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("secret_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    # -- Derived helpers ----------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return _split_csv(self.cors_origins)

    @property
    def enabled_symbol_list(self) -> list[str]:
        return [s.upper() for s in _split_csv(self.enabled_symbols)]

    @property
    def is_futures(self) -> bool:
        return self.binance_market_type == MarketType.FUTURES

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def has_api_credentials(self) -> bool:
        return bool(self.binance_api_key and self.binance_api_secret)

    @property
    def testing(self) -> bool:
        return self.app_env.lower() in {"test", "testing"} or bool(os.getenv("PYTEST_CURRENT_TEST"))


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()


def reload_settings() -> Settings:
    """Clear the settings cache (used by tests)."""
    get_settings.cache_clear()
    return get_settings()
