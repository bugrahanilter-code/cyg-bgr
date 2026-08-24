"""Risk configuration.

These values are the platform's safety envelope. They are intentionally
conservative by default and every one of them is editable from the dashboard.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.risk.exit_policy import StopLossMode, TakeProfitMode


class RiskConfig(BaseModel):
    """All risk limits in one validated object."""

    # -- per trade ----------------------------------------------------------
    risk_per_trade_pct: float = Field(default=0.5, gt=0.0, le=10.0)
    max_position_notional_pct: float = Field(default=100.0, gt=0.0, le=1000.0)
    max_total_exposure_pct: float = Field(default=200.0, gt=0.0, le=2000.0)
    #: Floor and ceiling for the leverage actually used on a position. The
    #: requested leverage is clamped into this band, so a market whose exchange
    #: cap is lower than min_leverage is sized at what the exchange allows
    #: rather than being forced past it.
    min_leverage: int = Field(default=1, ge=1, le=125)
    max_leverage: int = Field(default=3, ge=1, le=125)

    @model_validator(mode="after")
    def _leverage_band_is_ordered(self) -> RiskConfig:
        """A minimum above the maximum would silently invert the clamp."""
        if self.min_leverage > self.max_leverage:
            raise ValueError(
                f"min_leverage ({self.min_leverage}) cannot exceed "
                f"max_leverage ({self.max_leverage})"
            )
        return self

    margin_buffer_pct: float = Field(
        default=95.0, gt=0.0, le=100.0, description="Share of the free balance usable as margin"
    )

    # -- exits: stop loss and take profit ------------------------------------
    #: How the stop is chosen. "strategy" leaves the strategy's own level alone
    #: and is the default, so this whole block is inert until it is changed.
    stop_loss_mode: str = Field(default=StopLossMode.STRATEGY.value)
    #: Used when the mode is "fixed_pct", and as the fallback whenever a
    #: strategy produces a signal with no stop at all.
    stop_loss_pct: float = Field(default=2.0, gt=0.0, le=50.0)
    #: Safety envelope applied in every mode except "fixed_pct". A strategy
    #: asking for a 40% stop is a bug, not a choice. Set either to 0 to disable.
    min_stop_distance_pct: float = Field(default=0.3, ge=0.0, le=50.0)
    max_stop_distance_pct: float = Field(default=10.0, ge=0.0, le=100.0)

    #: How the target is chosen. "none" leaves the exit to the stop, the
    #: trailing stop or an exit signal, which is usually right for trend
    #: systems: a fixed target caps the few large winners that pay for the
    #: many small losses.
    take_profit_mode: str = Field(default=TakeProfitMode.STRATEGY.value)
    take_profit_pct: float = Field(default=4.0, gt=0.0, le=100.0)
    #: Used when the mode is "risk_multiple": 2.0 means a target twice as far
    #: away as the stop.
    take_profit_r_multiple: float = Field(default=2.0, gt=0.0, le=20.0)

    #: Reject an entry whose reward/risk is below this. 0 disables the check.
    min_risk_reward: float = Field(default=0.0, ge=0.0, le=20.0)

    #: Follow price with a stop once the trade moves in your favour.
    trailing_stop_enabled: bool = Field(default=False)
    #: Trail distance as a percentage of price. Applied when a strategy does
    #: not supply its own ATR based trail.
    trailing_stop_pct: float = Field(default=1.5, gt=0.0, le=50.0)
    #: Start trailing only after the trade is this far in profit, measured in R.
    #: 0 trails from the first bar.
    trailing_start_r: float = Field(default=1.0, ge=0.0, le=20.0)

    #: Move the stop to break even once the trade is this far in profit, in R.
    #: 0 disables it. This removes the risk on a trade but also converts some
    #: winners into scratches, which is a real cost, not a free improvement.
    break_even_at_r: float = Field(default=0.0, ge=0.0, le=20.0)

    @model_validator(mode="after")
    def _stop_band_is_ordered(self) -> RiskConfig:
        if (
            self.min_stop_distance_pct > 0
            and self.max_stop_distance_pct > 0
            and self.min_stop_distance_pct > self.max_stop_distance_pct
        ):
            raise ValueError(
                f"min_stop_distance_pct ({self.min_stop_distance_pct}) cannot exceed "
                f"max_stop_distance_pct ({self.max_stop_distance_pct})"
            )
        return self

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
