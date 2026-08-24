"""Realistic trading cost model.

A backtest without costs is a marketing brochure, not a research tool. Fees,
spread/slippage, funding and execution delay are all modelled explicitly and
are all visible in the result.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.constants import SignalType


class CostModel(BaseModel):
    """Every cost applied by the backtester and the paper trading engine."""

    taker_fee_pct: float = Field(default=0.04, ge=0.0, le=1.0)
    maker_fee_pct: float = Field(default=0.02, ge=0.0, le=1.0)
    slippage_pct: float = Field(default=0.02, ge=0.0, le=5.0)
    funding_rate_pct_per_8h: float = Field(default=0.01, ge=-1.0, le=1.0)
    #: Number of bars between the decision and the fill. 1 means the signal of
    #: a closed candle is filled at the open of the NEXT candle.
    execution_delay_bars: int = Field(default=1, ge=1, le=10)
    apply_funding: bool = Field(default=True)

    @classmethod
    def from_settings(cls) -> CostModel:
        settings = get_settings()
        return cls(
            taker_fee_pct=settings.taker_fee_pct,
            maker_fee_pct=settings.maker_fee_pct,
            slippage_pct=settings.slippage_pct,
            funding_rate_pct_per_8h=settings.funding_rate_pct_per_8h,
        )

    def fill_price(self, price: float, side: SignalType | str, is_entry: bool = True) -> float:
        """Apply slippage in the direction that always hurts the trader."""
        direction = str(getattr(side, "value", side)).upper()
        factor = self.slippage_pct / 100.0
        buying = (direction == "LONG" and is_entry) or (direction == "SHORT" and not is_entry)
        return price * (1.0 + factor) if buying else price * (1.0 - factor)

    def fee_for(self, notional: float, maker: bool = False) -> float:
        """Fee charged for one side of a trade."""
        rate = self.maker_fee_pct if maker else self.taker_fee_pct
        return abs(notional) * rate / 100.0
