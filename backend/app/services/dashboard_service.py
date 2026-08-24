"""Everything the overview page needs, assembled in one query pass."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import EmergencyStopLevel, TradingMode
from app.core.time_utils import utcnow
from app.models.account import BalanceSnapshot
from app.models.trading import Position, Trade
from app.portfolio.engine import PortfolioEngine
from app.services import analytics_service, bot_state_service, settings_service


def _position_payload(position: Position, price: float | None) -> dict[str, Any]:
    entry = float(position.entry_price)
    quantity = float(position.quantity)
    current = price if price and price > 0 else entry
    direction = 1.0 if position.side == "LONG" else -1.0
    unrealized = (current - entry) * quantity * direction
    margin = float(position.margin or 0.0)
    return {
        "id": position.id,
        "uid": position.uid,
        "symbol": position.symbol,
        "side": position.side,
        "status": position.status,
        "strategy": position.strategy_key,
        "quantity": quantity,
        "entry_price": entry,
        "current_price": current,
        "stop_loss": position.stop_loss,
        "take_profit": position.take_profit,
        "trailing_stop": position.trailing_stop,
        "leverage": float(position.leverage or 1.0),
        "margin": margin,
        "liquidation_price": position.liquidation_price,
        "unrealized_pnl": unrealized,
        "unrealized_pnl_pct": (unrealized / margin * 100.0) if margin > 0 else 0.0,
        "notional": entry * quantity,
        "opened_at": position.opened_at,
        "market_regime": position.market_regime,
        "signal_confidence": float(position.signal_confidence or 0.0),
        "entry_reason": position.entry_reason,
        "mode": position.mode,
    }


def open_positions_payload(db: Session, mode: TradingMode, price_lookup) -> list[dict[str, Any]]:
    """Open positions enriched with live prices."""
    portfolio = PortfolioEngine(mode)
    return [
        _position_payload(position, price_lookup(position.symbol))
        for position in portfolio.open_positions(db)
    ]


def recent_trades_payload(db: Session, mode: TradingMode, limit: int = 10) -> list[dict[str, Any]]:
    """Most recent closed trades."""
    trades = (
        db.execute(
            select(Trade)
            .where(Trade.mode == mode.value)
            .order_by(Trade.closed_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": trade.id,
            "uid": trade.uid,
            "symbol": trade.symbol,
            "strategy": trade.strategy_key,
            "side": trade.side,
            "quantity": float(trade.quantity),
            "entry_price": float(trade.entry_price),
            "exit_price": float(trade.exit_price),
            "net_pnl": float(trade.net_pnl or 0.0),
            "return_pct": float(trade.return_pct or 0.0),
            "fees": float(trade.fees or 0.0),
            "funding": float(trade.funding or 0.0),
            "is_win": bool(trade.is_win),
            "opened_at": trade.opened_at,
            "closed_at": trade.closed_at,
            "duration_seconds": int(trade.duration_seconds or 0),
            "exit_reason": trade.exit_reason,
            "market_regime": trade.market_regime,
            "mode": trade.mode,
        }
        for trade in trades
    ]


def build_overview(db: Session, context) -> dict[str, Any]:
    """Assemble the overview payload."""
    trading_config = settings_service.get_trading_config(db)
    risk_config = settings_service.get_risk_config(db)
    state = bot_state_service.get_state(db)
    mode = TradingMode(state.mode) if state.mode else trading_config.mode
    portfolio = PortfolioEngine(mode)
    market_data = getattr(context, "market_data", None)

    def price_lookup(symbol: str):
        return market_data.last_price(symbol) if market_data else None

    account = portfolio.account_state(db, price_lookup)
    stats = portfolio.daily_stats(db)
    positions = open_positions_payload(db, mode, price_lookup)

    peak_equity = max(
        float(stats.peak_equity or 0.0), float(stats.starting_equity or 0.0), account.equity
    )
    drawdown_pct = (
        max(0.0, (peak_equity - account.equity) / peak_equity * 100.0) if peak_equity > 0 else 0.0
    )
    starting_equity = float(stats.starting_equity or 0.0)
    daily_return_pct = (
        float(stats.realized_pnl or 0.0) / starting_equity * 100.0 if starting_equity > 0 else 0.0
    )

    equity_points = (
        db.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.mode == mode.value)
            .order_by(BalanceSnapshot.taken_at.desc())
            .limit(500)
        )
        .scalars()
        .all()
    )
    engine = getattr(context, "engine", None)

    return {
        "generated_at": utcnow(),
        "bot": {
            "status": state.status,
            "mode": mode.value,
            "emergency_stop_level": state.emergency_stop_level,
            "emergency_stop_active": state.emergency_stop_level != EmergencyStopLevel.NONE.value,
            "live_trading_confirmed": bool(state.live_trading_confirmed),
            "halt_reason": state.halt_reason,
            "last_heartbeat": state.last_heartbeat,
            "engine": engine.status() if engine else {},
        },
        "account": {
            "balance": account.balance,
            "available_balance": account.available,
            "used_margin": account.used_margin,
            "unrealized_pnl": account.unrealized_pnl,
            "equity": account.equity,
        },
        "pnl": {
            "realized_today": float(stats.realized_pnl or 0.0),
            "daily_return_pct": daily_return_pct,
            "weekly": analytics_service.pnl_since(db, mode, 7),
            "monthly": analytics_service.pnl_since(db, mode, 30),
            "unrealized": account.unrealized_pnl,
            "fees_today": float(stats.fees or 0.0),
            "funding_today": float(stats.funding or 0.0),
        },
        "risk": {
            "daily_profit_target_pct": risk_config.daily_profit_target_pct,
            "daily_loss_limit_pct": risk_config.daily_loss_limit_pct,
            "daily_target_progress_pct": (
                daily_return_pct / risk_config.daily_profit_target_pct * 100.0
                if risk_config.daily_profit_target_pct > 0
                else 0.0
            ),
            "daily_target_reached": daily_return_pct >= risk_config.daily_profit_target_pct,
            "daily_loss_limit_reached": daily_return_pct <= -abs(risk_config.daily_loss_limit_pct),
            "current_drawdown_pct": drawdown_pct,
            "max_drawdown_pct": risk_config.max_drawdown_pct,
            "trades_today": int(stats.trades_count or 0),
            "max_trades_per_day": risk_config.max_trades_per_day,
            "consecutive_losses": int(stats.consecutive_losses or 0),
            "max_consecutive_losses": risk_config.max_consecutive_losses,
            "open_positions": len(positions),
            "max_concurrent_positions": risk_config.max_concurrent_positions,
            "blocked_reasons": engine.snapshot.blocked_reasons if engine else [],
        },
        "positions": positions,
        "recent_trades": recent_trades_payload(db, mode, limit=10),
        "equity_curve": [
            {"time": point.taken_at, "equity": float(point.equity)}
            for point in reversed(equity_points)
        ],
        "symbols": trading_config.enabled_symbols,
        "prices": {symbol: price_lookup(symbol) for symbol in trading_config.enabled_symbols},
    }
