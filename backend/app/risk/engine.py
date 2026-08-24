"""Risk Engine.

The most important component of the platform. A strategy can be as confident
as it likes: if the Risk Engine says no, no order is ever created.

The engine is a pure function of (signal, context): no database, no network.
That makes every rule directly unit testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.constants import (
    EmergencyStopLevel,
    RiskRejectionCode,
    SignalType,
    TradingMode,
    VolatilityRegime,
)
from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.exchange.filters import SymbolFilters, default_filters_for
from app.regime.engine import RegimeResult
from app.risk.config import RiskConfig
from app.risk.position_sizing import PositionSizing, calculate_position_size
from app.signals.models import StrategySignal

logger = get_logger(__name__)


@dataclass(slots=True)
class OpenPositionInfo:
    """Minimal view of an open position needed by the risk rules."""

    symbol: str
    side: SignalType
    notional: float
    margin: float = 0.0


@dataclass(slots=True)
class RiskContext:
    """Everything the risk rules need to know about the current state."""

    equity: float = 0.0
    available_balance: float = 0.0
    mode: TradingMode = TradingMode.PAPER
    open_positions: list[OpenPositionInfo] = field(default_factory=list)

    daily_start_equity: float = 0.0
    daily_realized_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    last_loss_at: datetime | None = None
    peak_equity: float = 0.0

    market_data_stale: bool = False
    reconciliation_ok: bool = True
    emergency_stop: EmergencyStopLevel = EmergencyStopLevel.NONE
    trading_enabled: bool = True
    live_trading_confirmed: bool = False
    symbol_enabled: bool = True
    strategy_enabled: bool = True

    spread_pct: float | None = None
    leverage: float = 1.0
    filters: SymbolFilters | None = None
    regime: RegimeResult | None = None
    now: datetime = field(default_factory=utcnow)

    @property
    def open_notional(self) -> float:
        return sum(position.notional for position in self.open_positions)

    @property
    def daily_return_pct(self) -> float:
        if self.daily_start_equity <= 0:
            return 0.0
        return self.daily_realized_pnl / self.daily_start_equity * 100.0

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100.0)


@dataclass(slots=True)
class RiskRejection:
    """One reason why a signal was refused."""

    code: RiskRejectionCode
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code.value, "message": self.message}


@dataclass(slots=True)
class RiskDecision:
    """The verdict of the Risk Engine."""

    approved: bool = False
    rejections: list[RiskRejection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sizing: PositionSizing | None = None

    @property
    def codes(self) -> list[str]:
        return [rejection.code.value for rejection in self.rejections]

    @property
    def summary(self) -> str:
        if self.approved:
            return "Approved"
        return "; ".join(rejection.message for rejection in self.rejections) or "Rejected"

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "rejections": [rejection.to_dict() for rejection in self.rejections],
            "warnings": self.warnings,
            "sizing": self.sizing.to_dict() if self.sizing else None,
        }


class RiskEngine:
    """Applies every risk rule to a candidate signal."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    # -- gate used before any strategy even runs ---------------------------
    def can_open_new_positions(self, context: RiskContext) -> RiskDecision:
        """Portfolio level checks that do not depend on a specific signal."""
        decision = RiskDecision(approved=True)
        config = self.config

        if context.emergency_stop != EmergencyStopLevel.NONE:
            self._reject(
                decision,
                RiskRejectionCode.EMERGENCY_STOP,
                f"Emergency stop active ({context.emergency_stop.value})",
            )
        if not context.trading_enabled:
            self._reject(decision, RiskRejectionCode.TRADING_DISABLED, "Trading is disabled")
        if context.mode == TradingMode.LIVE and not context.live_trading_confirmed:
            self._reject(
                decision,
                RiskRejectionCode.LIVE_TRADING_NOT_ENABLED,
                "Live trading has not been explicitly confirmed",
            )
        if config.block_on_stale_data and context.market_data_stale:
            self._reject(
                decision, RiskRejectionCode.STALE_MARKET_DATA, "Market data is stale"
            )
        if not context.reconciliation_ok:
            self._reject(
                decision,
                RiskRejectionCode.RECONCILIATION_MISMATCH,
                "Local state does not match the exchange",
            )

        if context.daily_return_pct <= -abs(config.daily_loss_limit_pct):
            self._reject(
                decision,
                RiskRejectionCode.DAILY_LOSS_LIMIT_REACHED,
                f"Daily loss limit reached ({context.daily_return_pct:.2f} percent)",
            )
        if context.daily_return_pct >= config.daily_profit_target_pct:
            self._reject(
                decision,
                RiskRejectionCode.DAILY_PROFIT_TARGET_REACHED,
                f"Daily profit target reached ({context.daily_return_pct:.2f} percent)",
            )
        if context.trades_today >= config.max_trades_per_day:
            self._reject(
                decision,
                RiskRejectionCode.MAX_TRADES_PER_DAY,
                f"Maximum of {config.max_trades_per_day} trades per day reached",
            )
        if context.consecutive_losses >= config.max_consecutive_losses:
            self._reject(
                decision,
                RiskRejectionCode.MAX_CONSECUTIVE_LOSSES,
                f"{context.consecutive_losses} consecutive losses: trading paused",
            )
        if self._in_cooldown(context):
            self._reject(
                decision,
                RiskRejectionCode.COOLDOWN_ACTIVE,
                f"Cooldown active for {config.cooldown_minutes} minutes after a loss",
            )
        if context.drawdown_pct >= config.max_drawdown_pct:
            self._reject(
                decision,
                RiskRejectionCode.MAX_DRAWDOWN_REACHED,
                f"Maximum drawdown reached ({context.drawdown_pct:.2f} percent)",
            )
        if len(context.open_positions) >= config.max_concurrent_positions:
            self._reject(
                decision,
                RiskRejectionCode.MAX_CONCURRENT_POSITIONS,
                f"Already holding {len(context.open_positions)} positions",
            )
        return decision

    def _in_cooldown(self, context: RiskContext) -> bool:
        if self.config.cooldown_minutes <= 0 or context.last_loss_at is None:
            return False
        if context.consecutive_losses <= 0:
            return False
        deadline = context.last_loss_at + timedelta(minutes=self.config.cooldown_minutes)
        return context.now < deadline

    # -- full evaluation of one signal --------------------------------------
    def evaluate(self, signal: StrategySignal, context: RiskContext) -> RiskDecision:
        """Approve or reject a signal and, when approved, size the position."""
        if not signal.is_entry:
            decision = RiskDecision(approved=False)
            self._reject(
                decision, RiskRejectionCode.TRADING_DISABLED, "Signal is not an entry signal"
            )
            return decision

        decision = self.can_open_new_positions(context)
        config = self.config

        if not context.symbol_enabled:
            self._reject(
                decision, RiskRejectionCode.SYMBOL_DISABLED, f"{signal.symbol} is disabled"
            )
        if not context.strategy_enabled:
            self._reject(
                decision,
                RiskRejectionCode.STRATEGY_DISABLED,
                f"Strategy {signal.strategy_key} is disabled",
            )
        if config.one_position_per_symbol and any(
            position.symbol == signal.symbol for position in context.open_positions
        ):
            self._reject(
                decision,
                RiskRejectionCode.POSITION_ALREADY_OPEN,
                f"A position on {signal.symbol} is already open",
            )
        if signal.confidence < config.min_signal_confidence:
            self._reject(
                decision,
                RiskRejectionCode.LOW_CONFIDENCE,
                f"Confidence {signal.confidence:.2f} below the minimum "
                f"{config.min_signal_confidence:.2f}",
            )
        if (
            config.block_on_extreme_volatility
            and context.regime is not None
            and context.regime.volatility == VolatilityRegime.EXTREME
        ):
            self._reject(
                decision,
                RiskRejectionCode.EXTREME_VOLATILITY,
                "Extreme volatility regime: new positions blocked",
            )
        if context.spread_pct is not None and context.spread_pct > config.max_spread_pct:
            self._reject(
                decision,
                RiskRejectionCode.SPREAD_TOO_WIDE,
                f"Spread {context.spread_pct:.3f} percent above the "
                f"{config.max_spread_pct} percent limit",
            )

        leverage = min(max(context.leverage, 1.0), float(config.max_leverage))
        if context.leverage > config.max_leverage:
            decision.warnings.append(
                f"Leverage reduced from {context.leverage} to the configured maximum "
                f"{config.max_leverage}"
            )

        if signal.entry_price is None or signal.stop_loss is None:
            self._reject(
                decision,
                RiskRejectionCode.INVALID_STOP_LOSS,
                "The signal has no entry price or no stop loss",
            )
            decision.approved = False
            return decision

        filters = context.filters or default_filters_for(signal.symbol)
        sizing = calculate_position_size(
            equity=context.equity,
            available_balance=context.available_balance,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            side=signal.signal,
            filters=filters,
            risk_per_trade_pct=config.risk_per_trade_pct,
            max_position_notional_pct=config.max_position_notional_pct,
            max_total_exposure_pct=config.max_total_exposure_pct,
            current_exposure=context.open_notional,
            leverage=leverage,
            margin_buffer_pct=config.margin_buffer_pct,
            taker_fee_pct=config.taker_fee_pct,
        )
        decision.sizing = sizing
        if not sizing.valid:
            self._reject(
                decision,
                sizing.rejection_code or RiskRejectionCode.POSITION_SIZE_TOO_SMALL,
                sizing.reason,
            )

        decision.approved = not decision.rejections
        if decision.approved:
            logger.info(
                "Risk approved signal",
                extra={
                    "symbol": signal.symbol,
                    "strategy": signal.strategy_key,
                    "side": signal.signal.value,
                    "quantity": sizing.quantity,
                    "notional": round(sizing.notional, 2),
                    "risk_amount": round(sizing.risk_amount, 2),
                },
            )
        else:
            logger.info(
                "Risk rejected signal",
                extra={
                    "symbol": signal.symbol,
                    "strategy": signal.strategy_key,
                    "codes": decision.codes,
                },
            )
        return decision

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _reject(decision: RiskDecision, code: RiskRejectionCode, message: str) -> None:
        decision.approved = False
        if code.value not in decision.codes:
            decision.rejections.append(RiskRejection(code=code, message=message))
