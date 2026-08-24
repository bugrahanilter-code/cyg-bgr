"""Risk configuration.

These values are the platform's safety envelope. They are intentionally
conservative by default and every one of them is editable from the dashboard.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.config import get_settings


class RiskConfig(BaseModel):
    """All risk limits in one validated object."""

    # -- per trade ----------------------------------------------------------
    risk_per_trade_pct: float = Field(default=0.5, gt=0.0, le=10.0)
    max_position_notional_pct: float = Field(default=100.0, gt=0.0, le=1000.0)
    max_total_exposure_pct: float = Field(default=200.0, gt=0.0, le=2000.0)
    max_leverage: int = Field(default=3, ge=1, le=125)
    margin_buffer_pct: float = Field(
        default=95.0, gt=0.0, le=100.0, description="Share of the free balance usable as margin"
    )

    # -- per day ------------------------------------------------------------
    daily_profit_target_pct: float = Field(default=2.0, gt=0.0, le=100.0)
    daily_loss_limit_pct: float = Field(default=1.5, gt=0.0, le=100.0)
    max_trades_per_day: int = Field(default=15, ge=1, le=500)

    # -- streaks and drawdown ----------------------------------------------
    max_consecutive_losses: int = Field(default=3, ge=1, le=50)
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)
    max_drawdown_pct: float = Field(default=15.0, gt=0.0, le=100.0)

    # -- concurrency --------------------------------------------------------
    max_concurrent_positions: int = Field(default=2, ge=1, le=50)
    one_position_per_symbol: bool = Field(default=True)

    # -- market quality -----------------------------------------------------
    min_signal_confidence: float = Field(default=0.35, ge=0.0, le=1.0)
    max_spread_pct: float = Field(default=0.15, gt=0.0, le=10.0)
    block_on_extreme_volatility: bool = Field(default=True)
    block_on_stale_data: bool = Field(default=True)

    # -- costs used for sizing estimates ------------------------------------
    taker_fee_pct: float = Field(default=0.04, ge=0.0, le=1.0)
    slippage_pct: float = Field(default=0.02, ge=0.0, le=5.0)

    @classmethod
    def from_settings(cls) -> RiskConfig:
        """Build the default configuration from the environment settings."""
        settings = get_settings()
        return cls(
            risk_per_trade_pct=settings.risk_per_trade_pct,
            max_position_notional_pct=settings.max_position_notional_pct,
            max_total_exposure_pct=settings.max_total_exposure_pct,
            max_leverage=settings.max_leverage,
            daily_profit_target_pct=settings.daily_profit_target_pct,
            daily_loss_limit_pct=settings.daily_loss_limit_pct,
            max_trades_per_day=settings.max_trades_per_day,
            max_consecutive_losses=settings.max_consecutive_losses,
            cooldown_minutes=settings.cooldown_minutes,
            max_drawdown_pct=settings.max_drawdown_pct,
            max_concurrent_positions=settings.max_concurrent_positions,
            min_signal_confidence=settings.min_signal_confidence,
            max_spread_pct=settings.max_spread_pct,
            taker_fee_pct=settings.taker_fee_pct,
            slippage_pct=settings.slippage_pct,
        )


DEFAULT_RISK_CONFIG_KEY = "risk_config"
