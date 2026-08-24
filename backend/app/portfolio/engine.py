"""Portfolio Engine.

Owns the local truth about positions, balances and daily statistics for every
trading mode. Paper trading and live trading use exactly the same code path,
which is what keeps their reports comparable.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import ExitReason, PositionStatus, PositionSide, TradingMode
from app.core.logging import get_logger
from app.core.time_utils import day_start, today_utc, utcnow
from app.models.account import BalanceSnapshot, DailyStatistic
from app.models.trading import Position, Trade
from app.portfolio.pnl import compute_trade_pnl, unrealized_pnl
from app.services.settings_service import get_json_setting, set_json_setting

logger = get_logger(__name__)

PAPER_ACCOUNT_KEY = "paper_account"
PriceLookup = Callable[[str], float | None]


@dataclass(slots=True)
class AccountState:
    """Snapshot of the account for one trading mode."""

    balance: float = 0.0
    available: float = 0.0
    unrealized_pnl: float = 0.0
    used_margin: float = 0.0

    @property
    def equity(self) -> float:
        return self.balance + self.unrealized_pnl


class PortfolioEngine:
    """Position bookkeeping, balances and daily statistics."""

    def __init__(self, mode: TradingMode = TradingMode.PAPER) -> None:
        self.mode = mode

    # -- positions ----------------------------------------------------------
    def open_positions(self, db: Session, symbol: str | None = None) -> list[Position]:
        """Every position currently open in this mode."""
        query = select(Position).where(
            Position.mode == self.mode.value, Position.status == PositionStatus.OPEN.value
        )
        if symbol:
            query = query.where(Position.symbol == symbol)
        return list(db.execute(query).scalars().all())

    def get_position(self, db: Session, symbol: str) -> Position | None:
        positions = self.open_positions(db, symbol)
        return positions[0] if positions else None

    def create_position(
        self,
        db: Session,
        *,
        symbol: str,
        side: PositionSide,
        quantity: float,
        entry_price: float,
        stop_loss: float | None,
        take_profit: float | None,
        leverage: float,
        margin: float,
        strategy_key: str,
        signal_id: int | None = None,
        entry_reason: str = "",
        market_regime: str = "UNKNOWN",
        signal_confidence: float = 0.0,
        fees_paid: float = 0.0,
        slippage_cost: float = 0.0,
        liquidation_price: float | None = None,
        opened_at: datetime | None = None,
        meta: dict | None = None,
    ) -> Position:
        """Persist a newly opened position."""
        position = Position(
            uid=uuid.uuid4().hex[:24],
            symbol=symbol,
            mode=self.mode.value,
            strategy_key=strategy_key,
            side=side.value,
            status=PositionStatus.OPEN.value,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=leverage,
            margin=margin,
            liquidation_price=liquidation_price,
            fees_paid=fees_paid,
            slippage_cost=slippage_cost,
            highest_price=entry_price,
            lowest_price=entry_price,
            opened_at=opened_at or utcnow(),
            signal_id=signal_id,
            entry_reason=entry_reason,
            market_regime=market_regime,
            signal_confidence=signal_confidence,
            meta=meta or {},
        )
        db.add(position)
        db.commit()
        db.refresh(position)
        logger.info(
            "Position opened",
            extra={
                "symbol": symbol,
                "side": side.value,
                "quantity": quantity,
                "entry": entry_price,
                "mode": self.mode.value,
            },
        )
        return position

    def mark_to_market(self, db: Session, price_lookup: PriceLookup) -> float:
        """Refresh the unrealised PnL of every open position."""
        total = 0.0
        positions = self.open_positions(db)
        for position in positions:
            price = price_lookup(position.symbol)
            if price is None or price <= 0:
                total += float(position.unrealized_pnl or 0.0)
                continue
            pnl = unrealized_pnl(position.side, position.entry_price, price, position.quantity)
            position.unrealized_pnl = pnl
            position.highest_price = max(float(position.highest_price or price), price)
            position.lowest_price = min(float(position.lowest_price or price), price)
            total += pnl
        if positions:
            db.commit()
        return total

    def close_position(
        self,
        db: Session,
        position: Position,
        *,
        exit_price: float,
        exit_reason: ExitReason | str,
        exit_fees: float = 0.0,
        funding_paid: float = 0.0,
        slippage_cost: float = 0.0,
        exit_order_id: str | None = None,
        closed_at: datetime | None = None,
        timeframe: str = "",
        backtest_id: int | None = None,
    ) -> Trade:
        """Close a position, write the trade journal entry and update the account."""
        closed_at = closed_at or utcnow()
        fee_total = float(position.fees_paid or 0.0) + exit_fees
        funding_total = float(position.funding_paid or 0.0) + funding_paid
        slippage_total = float(position.slippage_cost or 0.0) + slippage_cost

        breakdown = compute_trade_pnl(
            side=position.side,
            entry_price=float(position.entry_price),
            exit_price=exit_price,
            quantity=float(position.quantity),
            fee_pct=0.0,  # explicit fee amounts are passed in below
            funding_paid=funding_total,
            slippage=slippage_total,
            capital_base=float(position.margin) or float(position.entry_price) * float(position.quantity),
        )
        net = breakdown.gross - fee_total - funding_total
        capital_base = float(position.margin) or (float(position.entry_price) * float(position.quantity))
        return_pct = (net / capital_base * 100.0) if capital_base > 0 else 0.0

        position.status = PositionStatus.CLOSED.value
        position.exit_price = exit_price
        position.closed_at = closed_at
        position.realized_pnl = net
        position.unrealized_pnl = 0.0
        position.fees_paid = fee_total
        position.funding_paid = funding_total
        position.slippage_cost = slippage_total
        position.exit_reason = str(getattr(exit_reason, "value", exit_reason))

        duration = max(0, int((closed_at - position.opened_at).total_seconds()))
        trade = Trade(
            uid=uuid.uuid4().hex[:24],
            position_id=position.id,
            exit_order_id=exit_order_id,
            backtest_id=backtest_id,
            symbol=position.symbol,
            strategy_key=position.strategy_key,
            mode=self.mode.value,
            timeframe=timeframe,
            side=position.side,
            quantity=float(position.quantity),
            entry_price=float(position.entry_price),
            exit_price=exit_price,
            leverage=float(position.leverage or 1.0),
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            notional=float(position.entry_price) * float(position.quantity),
            opened_at=position.opened_at,
            closed_at=closed_at,
            duration_seconds=duration,
            gross_pnl=breakdown.gross,
            fees=fee_total,
            funding=funding_total,
            slippage_cost=slippage_total,
            net_pnl=net,
            return_pct=return_pct,
            is_win=net > 0,
            signal_confidence=float(position.signal_confidence or 0.0),
            market_regime=position.market_regime,
            entry_reason=position.entry_reason,
            exit_reason=str(getattr(exit_reason, "value", exit_reason)),
        )
        db.add(trade)

        if self.mode != TradingMode.BACKTEST:
            self._apply_balance_change(db, net)
        self.record_daily_result(db, net, fees=fee_total, funding=funding_total, when=closed_at)

        db.commit()
        db.refresh(trade)
        logger.info(
            "Position closed",
            extra={
                "symbol": position.symbol,
                "side": position.side,
                "exit": exit_price,
                "net_pnl": round(net, 4),
                "reason": trade.exit_reason,
                "mode": self.mode.value,
            },
        )
        return trade

    # -- account ------------------------------------------------------------
    def account_state(self, db: Session, price_lookup: PriceLookup | None = None) -> AccountState:
        """Balance, margin usage and unrealised PnL for this mode."""
        positions = self.open_positions(db)
        used_margin = sum(float(position.margin or 0.0) for position in positions)
        if price_lookup is not None:
            unrealized = self.mark_to_market(db, price_lookup)
        else:
            unrealized = sum(float(position.unrealized_pnl or 0.0) for position in positions)

        balance = self.balance(db)
        return AccountState(
            balance=balance,
            available=max(balance - used_margin, 0.0),
            unrealized_pnl=unrealized,
            used_margin=used_margin,
        )

    def balance(self, db: Session) -> float:
        """Wallet balance for this mode."""
        if self.mode == TradingMode.LIVE:
            snapshot = db.execute(
                select(BalanceSnapshot)
                .where(BalanceSnapshot.mode == self.mode.value)
                .order_by(BalanceSnapshot.taken_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            return float(snapshot.total_balance) if snapshot else 0.0
        account = get_json_setting(db, PAPER_ACCOUNT_KEY, {})
        if "balance" not in account:
            starting = float(get_settings().paper_starting_balance)
            set_json_setting(db, PAPER_ACCOUNT_KEY, {"balance": starting, "starting": starting})
            return starting
        return float(account["balance"])

    def set_balance(self, db: Session, value: float) -> None:
        """Overwrite the paper balance (used by the reset endpoint)."""
        account = get_json_setting(db, PAPER_ACCOUNT_KEY, {})
        account["balance"] = float(value)
        account.setdefault("starting", float(value))
        set_json_setting(db, PAPER_ACCOUNT_KEY, account)

    def _apply_balance_change(self, db: Session, delta: float) -> None:
        if self.mode == TradingMode.LIVE:
            return  # the exchange is the source of truth for live balances
        account = get_json_setting(db, PAPER_ACCOUNT_KEY, {})
        starting = float(get_settings().paper_starting_balance)
        balance = float(account.get("balance", starting)) + float(delta)
        account["balance"] = balance
        account.setdefault("starting", starting)
        set_json_setting(db, PAPER_ACCOUNT_KEY, account)

    def record_balance_snapshot(
        self, db: Session, state: AccountState, source: str = "local"
    ) -> BalanceSnapshot:
        """Store an equity point for the dashboard curve."""
        snapshot = BalanceSnapshot(
            mode=self.mode.value,
            source=source,
            total_balance=state.balance,
            available_balance=state.available,
            unrealized_pnl=state.unrealized_pnl,
            equity=state.equity,
            taken_at=utcnow(),
        )
        db.add(snapshot)
        db.commit()
        return snapshot

    # -- daily statistics ---------------------------------------------------
    def daily_stats(self, db: Session, day: date | None = None) -> DailyStatistic:
        """Fetch (or create) the statistics row for a UTC day."""
        target = day or today_utc()
        stats = db.execute(
            select(DailyStatistic).where(
                DailyStatistic.mode == self.mode.value, DailyStatistic.day == target
            )
        ).scalar_one_or_none()
        if stats is None:
            balance = self.balance(db)
            stats = DailyStatistic(
                mode=self.mode.value,
                day=target,
                starting_equity=balance,
                ending_equity=balance,
                peak_equity=balance,
            )
            db.add(stats)
            db.commit()
            db.refresh(stats)
        return stats

    def record_daily_result(
        self,
        db: Session,
        net_pnl: float,
        *,
        fees: float = 0.0,
        funding: float = 0.0,
        when: datetime | None = None,
    ) -> DailyStatistic:
        """Update the daily aggregates after a trade is closed."""
        moment = when or utcnow()
        stats = self.daily_stats(db, day_start(moment).date())
        stats.trades_count += 1
        stats.realized_pnl = float(stats.realized_pnl or 0.0) + net_pnl
        stats.fees = float(stats.fees or 0.0) + fees
        stats.funding = float(stats.funding or 0.0) + funding
        if net_pnl > 0:
            stats.winning_trades += 1
            stats.consecutive_losses = 0
        else:
            stats.losing_trades += 1
            stats.consecutive_losses += 1
            stats.last_loss_at = moment

        starting = float(stats.starting_equity or 0.0)
        stats.ending_equity = starting + float(stats.realized_pnl or 0.0)
        stats.peak_equity = max(float(stats.peak_equity or starting), float(stats.ending_equity))
        if starting > 0:
            stats.daily_return_pct = float(stats.realized_pnl) / starting * 100.0
            drawdown = (float(stats.peak_equity) - float(stats.ending_equity)) / float(
                stats.peak_equity
            ) * 100.0
            stats.max_drawdown_pct = max(float(stats.max_drawdown_pct or 0.0), drawdown)
        db.commit()
        return stats
