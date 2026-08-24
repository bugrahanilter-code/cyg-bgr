"""Position sizing.

Size is NEVER derived from leverage alone. It comes from the distance to the
stop loss and the amount of equity the user is willing to risk, then it is
clamped by exposure, margin and exchange rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.constants import RiskRejectionCode, SignalType
from app.exchange.filters import SymbolFilters


@dataclass(slots=True)
class PositionSizing:
    """The full breakdown of a position size decision."""

    quantity: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    stop_distance: float = 0.0
    notional: float = 0.0
    margin: float = 0.0
    leverage: float = 1.0
    risk_amount: float = 0.0
    risk_pct_of_equity: float = 0.0
    estimated_fees: float = 0.0
    liquidation_price: float | None = None
    valid: bool = False
    rejection_code: RiskRejectionCode | None = None
    reason: str = ""
    caps_applied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "stop_distance": self.stop_distance,
            "notional": self.notional,
            "margin": self.margin,
            "leverage": self.leverage,
            "risk_amount": self.risk_amount,
            "risk_pct_of_equity": self.risk_pct_of_equity,
            "estimated_fees": self.estimated_fees,
            "liquidation_price": self.liquidation_price,
            "valid": self.valid,
            "reason": self.reason,
            "caps_applied": self.caps_applied,
        }


def estimate_liquidation_price(
    entry_price: float,
    side: SignalType,
    leverage: float,
    maintenance_margin_rate: float = 0.005,
) -> float | None:
    """Rough isolated-margin liquidation price estimate.

    This is an approximation for display and for sanity checks; Binance uses a
    tiered maintenance margin table that is not replicated here.
    """
    if leverage <= 0 or entry_price <= 0:
        return None
    initial_margin_rate = 1.0 / leverage
    if side == SignalType.LONG:
        return entry_price * (1.0 - initial_margin_rate + maintenance_margin_rate)
    return entry_price * (1.0 + initial_margin_rate - maintenance_margin_rate)


def max_safe_leverage(
    stop_distance_pct: float,
    maintenance_margin_rate: float = 0.005,
    buffer: float = 1.25,
) -> float:
    """Highest leverage at which the stop is still reached before liquidation.

    Leverage does not move a stop: a stop is a price, and a price does not care
    how much margin was posted. What leverage moves is the *liquidation* price,
    and it moves it toward the entry. At 20x liquidation sits about 4.5% away,
    so a 6% stop can never be reached - the exchange closes the position first
    and takes the whole margin instead of the amount that was meant to be
    risked.

    Nothing in the sizing formula needs high leverage: quantity comes from the
    risk budget divided by the stop distance. Leverage only decides how much
    margin is posted for that quantity. So when a stop is too wide for the
    requested leverage, lowering the leverage is free - the position size, the
    entry and the risk at the stop are all unchanged.

    ``buffer`` keeps a margin of safety between the stop and liquidation, so a
    stop is not merely reachable in theory but comfortably before the wick that
    would trigger liquidation.
    """
    distance = max(stop_distance_pct, 1e-9) / 100.0
    denominator = distance * buffer + maintenance_margin_rate
    if denominator <= 0:
        return 1.0
    return max(1.0, 1.0 / denominator)


def calculate_position_size(
    *,
    equity: float,
    available_balance: float,
    entry_price: float,
    stop_loss: float,
    side: SignalType,
    filters: SymbolFilters,
    risk_per_trade_pct: float,
    max_position_notional_pct: float,
    max_total_exposure_pct: float,
    current_exposure: float,
    leverage: float,
    margin_buffer_pct: float = 95.0,
    taker_fee_pct: float = 0.04,
) -> PositionSizing:
    """Compute a validated position size for one signal."""
    sizing = PositionSizing(entry_price=entry_price, stop_loss=stop_loss, leverage=leverage)

    if equity <= 0:
        sizing.reason = "Account equity is zero or negative"
        sizing.rejection_code = RiskRejectionCode.INSUFFICIENT_MARGIN
        return sizing
    if entry_price <= 0:
        sizing.reason = "Invalid entry price"
        sizing.rejection_code = RiskRejectionCode.INVALID_STOP_LOSS
        return sizing

    stop_distance = abs(entry_price - stop_loss)
    sizing.stop_distance = stop_distance
    if stop_distance <= 0:
        sizing.reason = "Stop loss must be different from the entry price"
        sizing.rejection_code = RiskRejectionCode.INVALID_STOP_LOSS
        return sizing
    if side == SignalType.LONG and stop_loss >= entry_price:
        sizing.reason = "A long stop loss must sit below the entry price"
        sizing.rejection_code = RiskRejectionCode.INVALID_STOP_LOSS
        return sizing
    if side == SignalType.SHORT and stop_loss <= entry_price:
        sizing.reason = "A short stop loss must sit above the entry price"
        sizing.rejection_code = RiskRejectionCode.INVALID_STOP_LOSS
        return sizing

    risk_amount = equity * risk_per_trade_pct / 100.0
    sizing.risk_amount = risk_amount
    quantity = risk_amount / stop_distance
    notional = quantity * entry_price

    # --- cap 1: maximum notional for a single position ---------------------
    max_notional = equity * max_position_notional_pct / 100.0
    if notional > max_notional:
        notional = max_notional
        quantity = notional / entry_price
        sizing.caps_applied.append("max_position_notional")

    # --- cap 2: total portfolio exposure -----------------------------------
    exposure_room = equity * max_total_exposure_pct / 100.0 - current_exposure
    if exposure_room <= 0:
        sizing.reason = "Maximum portfolio exposure already reached"
        sizing.rejection_code = RiskRejectionCode.MAX_EXPOSURE_EXCEEDED
        return sizing
    if notional > exposure_room:
        notional = exposure_room
        quantity = notional / entry_price
        sizing.caps_applied.append("max_total_exposure")

    # --- cap 3: available margin -------------------------------------------
    usable_margin = max(available_balance, 0.0) * margin_buffer_pct / 100.0
    max_notional_by_margin = usable_margin * max(leverage, 1.0)
    if max_notional_by_margin <= 0:
        sizing.reason = "No free margin available"
        sizing.rejection_code = RiskRejectionCode.INSUFFICIENT_MARGIN
        return sizing
    if notional > max_notional_by_margin:
        notional = max_notional_by_margin
        quantity = notional / entry_price
        sizing.caps_applied.append("available_margin")

    # --- exchange rules ----------------------------------------------------
    quantity = filters.round_quantity(quantity)
    if not filters.is_valid_quantity(quantity):
        sizing.quantity = quantity
        sizing.reason = (
            f"Position size {quantity} is below the exchange minimum {filters.min_quantity}"
        )
        sizing.rejection_code = RiskRejectionCode.POSITION_SIZE_TOO_SMALL
        return sizing
    if not filters.is_valid_notional(quantity, entry_price):
        sizing.quantity = quantity
        sizing.notional = quantity * entry_price
        sizing.reason = (
            f"Order value {sizing.notional:.2f} is below the exchange minimum "
            f"{filters.min_notional}"
        )
        sizing.rejection_code = RiskRejectionCode.MIN_NOTIONAL_NOT_MET
        return sizing

    notional = quantity * entry_price
    sizing.quantity = quantity
    sizing.notional = notional
    sizing.margin = notional / max(leverage, 1.0)
    sizing.risk_amount = min(risk_amount, quantity * stop_distance)
    sizing.risk_pct_of_equity = sizing.risk_amount / equity * 100.0
    sizing.estimated_fees = notional * taker_fee_pct / 100.0 * 2.0
    sizing.liquidation_price = estimate_liquidation_price(
        entry_price, side, leverage, filters.maintenance_margin_rate
    )
    sizing.valid = True
    sizing.reason = "Position size accepted"
    return sizing
