"""Where the stop loss and the take profit are finally decided.

A strategy proposes exit levels; this module decides them. Keeping that decision
in one pure function matters more than it looks: the backtester and the live
engine both call it, so a stop rule changed in Risk Settings changes the
simulation and the real orders together. If the two computed exits separately
they would drift apart, and a backtest that does not match the engine is worse
than no backtest.

Four modes, and the default changes nothing
-------------------------------------------
``STRATEGY`` (the default) passes the strategy's own levels through untouched,
so an existing installation behaves exactly as before this module existed.
The other modes let a user who does not want to edit fourteen strategies set one
rule for all of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.constants import SignalType, StrEnum


class StopLossMode(StrEnum):
    """How the stop distance is chosen."""

    #: Use whatever the strategy proposed. No interference.
    STRATEGY = "strategy"
    #: Ignore the strategy and place the stop a fixed percentage from entry.
    FIXED_PCT = "fixed_pct"
    #: Keep the strategy's stop but clamp it into a percentage band.
    BOUNDED = "bounded"


class TakeProfitMode(StrEnum):
    """How the target is chosen."""

    STRATEGY = "strategy"
    #: A fixed percentage from entry.
    FIXED_PCT = "fixed_pct"
    #: A multiple of the risk taken, e.g. 2R means twice the stop distance.
    RISK_MULTIPLE = "risk_multiple"
    #: No target at all: the trade is closed by the stop, the trailing stop or
    #: an exit signal. Useful for trend systems, where a fixed target caps the
    #: few large winners that pay for every small loss.
    NONE = "none"


@dataclass(slots=True)
class ExitLevels:
    """The decided levels plus what was done to them and why."""

    stop_loss: float
    take_profit: float | None
    #: Distance from entry to stop, in price.
    risk_distance: float
    #: Reward divided by risk, when there is a target.
    risk_reward: float | None
    #: Human readable record of every adjustment applied.
    adjustments: list[str] = field(default_factory=list)
    #: Set when the trade should not be taken at all.
    rejection: str | None = None

    @property
    def valid(self) -> bool:
        return self.rejection is None and self.risk_distance > 0

    def to_dict(self) -> dict:
        return {
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_distance": self.risk_distance,
            "risk_reward": self.risk_reward,
            "adjustments": self.adjustments,
            "rejection": self.rejection,
        }


def _signed(side: SignalType | str) -> int:
    """+1 for a long, -1 for a short, so one formula covers both directions."""
    value = str(getattr(side, "value", side)).upper()
    return -1 if value == "SHORT" else 1


def resolve_exits(
    config,
    *,
    side: SignalType | str,
    entry_price: float,
    proposed_stop: float | None,
    proposed_take_profit: float | None,
) -> ExitLevels:
    """Decide the final stop and target for one entry.

    ``config`` is a :class:`~app.risk.config.RiskConfig`. The function is pure:
    same inputs, same output, no database and no clock, which is what lets the
    backtester and the live engine share it.
    """
    direction = _signed(side)
    adjustments: list[str] = []

    # --- stop loss ---------------------------------------------------------
    stop = _resolve_stop(config, direction, entry_price, proposed_stop, adjustments)
    if stop is None:
        return ExitLevels(
            stop_loss=0.0,
            take_profit=None,
            risk_distance=0.0,
            risk_reward=None,
            adjustments=adjustments,
            rejection="No stop loss could be determined for this entry",
        )

    risk_distance = abs(entry_price - stop)
    if risk_distance <= 0:
        return ExitLevels(
            stop_loss=stop,
            take_profit=None,
            risk_distance=0.0,
            risk_reward=None,
            adjustments=adjustments,
            rejection="The stop loss sits on the entry price",
        )

    # --- take profit -------------------------------------------------------
    target = _resolve_target(
        config, direction, entry_price, risk_distance, proposed_take_profit, adjustments
    )

    risk_reward = abs(target - entry_price) / risk_distance if target is not None else None

    # --- risk/reward gate --------------------------------------------------
    rejection = None
    if (
        config.min_risk_reward > 0
        and risk_reward is not None
        and risk_reward < config.min_risk_reward
    ):
        rejection = (
            f"Reward/risk {risk_reward:.2f} is below the required {config.min_risk_reward:.2f}"
        )

    return ExitLevels(
        stop_loss=stop,
        take_profit=target,
        risk_distance=risk_distance,
        risk_reward=risk_reward,
        adjustments=adjustments,
        rejection=rejection,
    )


def _resolve_stop(
    config, direction: int, entry_price: float, proposed: float | None, adjustments: list[str]
) -> float | None:
    """Apply the configured stop rule, then the distance band in every mode."""
    mode = StopLossMode(config.stop_loss_mode)

    if mode is StopLossMode.FIXED_PCT:
        stop = entry_price * (1 - direction * config.stop_loss_pct / 100.0)
        adjustments.append(f"stop set to a fixed {config.stop_loss_pct:g}% from entry")
    else:
        if proposed is None or proposed <= 0:
            # Even in STRATEGY mode there has to be a stop. Falling back to the
            # configured percentage is safer than trading without one.
            stop = entry_price * (1 - direction * config.stop_loss_pct / 100.0)
            adjustments.append(
                f"strategy proposed no stop, using the configured {config.stop_loss_pct:g}%"
            )
        else:
            stop = proposed

    # The band is enforced in BOUNDED mode, and also in STRATEGY mode as a
    # safety envelope: a strategy asking for a 40% stop is a bug, not a choice.
    if mode is not StopLossMode.FIXED_PCT:
        distance_pct = abs(entry_price - stop) / entry_price * 100.0
        floor = config.min_stop_distance_pct
        ceiling = config.max_stop_distance_pct
        if floor > 0 and distance_pct < floor:
            stop = entry_price * (1 - direction * floor / 100.0)
            adjustments.append(f"stop widened from {distance_pct:.2f}% to the {floor:g}% minimum")
        elif ceiling > 0 and distance_pct > ceiling:
            stop = entry_price * (1 - direction * ceiling / 100.0)
            adjustments.append(
                f"stop tightened from {distance_pct:.2f}% to the {ceiling:g}% maximum"
            )
    return stop


def _resolve_target(
    config,
    direction: int,
    entry_price: float,
    risk_distance: float,
    proposed: float | None,
    adjustments: list[str],
) -> float | None:
    mode = TakeProfitMode(config.take_profit_mode)

    if mode is TakeProfitMode.NONE:
        if proposed is not None:
            adjustments.append("take profit removed: exits are left to the stop and signals")
        return None

    if mode is TakeProfitMode.FIXED_PCT:
        adjustments.append(f"target set to a fixed {config.take_profit_pct:g}% from entry")
        return entry_price * (1 + direction * config.take_profit_pct / 100.0)

    if mode is TakeProfitMode.RISK_MULTIPLE:
        adjustments.append(f"target set to {config.take_profit_r_multiple:g}R from entry")
        return entry_price + direction * risk_distance * config.take_profit_r_multiple

    if proposed is None or proposed <= 0:
        return None
    return proposed


def update_stop(
    config,
    *,
    side: SignalType | str,
    entry_price: float,
    current_stop: float,
    risk_distance: float,
    best_price: float,
    strategy_trail: float | None = None,
) -> tuple[float, str | None]:
    """Move a stop forward as a trade goes into profit.

    Returns ``(stop, reason)`` where ``reason`` names the rule that moved it, or
    None if nothing changed. Shared by the backtester and the live engine for
    the same reason :func:`resolve_exits` is: a trailing rule that behaves
    differently in the simulation makes the simulation worthless.

    A stop only ever moves in the profitable direction. Loosening a stop to
    avoid being taken out is how a small loss becomes a large one, so it is not
    possible here.
    """
    direction = _signed(side)
    if risk_distance <= 0:
        return current_stop, None

    profit_r = (best_price - entry_price) * direction / risk_distance
    candidate = current_stop
    reason: str | None = None

    # Break even first: it is a floor the trail can only improve on.
    if (
        config.break_even_at_r > 0
        and profit_r >= config.break_even_at_r
        and _is_better(entry_price, candidate, direction)
    ):
        candidate = entry_price
        reason = f"stop moved to break even at {profit_r:.2f}R"

    if config.trailing_stop_enabled and profit_r >= config.trailing_start_r:
        # A strategy supplied trail (usually ATR based) wins over the flat
        # percentage: it already accounts for the market's own volatility.
        if strategy_trail is not None and strategy_trail > 0:
            trailed = best_price - direction * strategy_trail
        else:
            trailed = best_price * (1 - direction * config.trailing_stop_pct / 100.0)
        if _is_better(trailed, candidate, direction):
            candidate = trailed
            reason = f"trailing stop at {profit_r:.2f}R of profit"

    return candidate, reason


def _is_better(candidate: float, current: float, direction: int) -> bool:
    """True when the candidate stop is tighter, i.e. closer to the profit side."""
    return candidate > current if direction > 0 else candidate < current
