"""Trading mode control, live trading activation and paper account reset."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Context, DbSession
from app.core.config import get_settings
from app.core.constants import EventSeverity, TradingMode
from app.models.trading import Order, Position, Signal, Trade
from app.portfolio.engine import PortfolioEngine
from app.schemas.common import MessageResponse
from app.schemas.requests import LiveTradingRequest, PaperResetRequest
from app.services import bot_state_service, credentials_service, event_service, settings_service

router = APIRouter(prefix="/trading", tags=["trading"])

LIVE_CHECKLIST = [
    "Binance API key and secret are stored",
    "The connection test succeeded",
    "The withdrawal permission is disabled on the key",
    "Risk settings have been reviewed",
    "You understand that no strategy guarantees a profit",
]


@router.get("/live/checklist", summary="What is still missing before live trading")
def live_checklist(db: DbSession, context: Context) -> dict[str, Any]:
    settings = get_settings()
    credentials = credentials_service.resolve_credentials(db)
    view = credentials_service.masked_view(db)
    state = bot_state_service.get_state(db)
    items = [
        {"key": "credentials", "label": LIVE_CHECKLIST[0], "done": credentials.is_present},
        {"key": "connection", "label": LIVE_CHECKLIST[1], "done": bool(view.get("last_test_ok"))},
        {
            "key": "withdrawal",
            "label": LIVE_CHECKLIST[2],
            "done": not view.get("withdrawal_permission_warning", False),
        },
        {"key": "risk", "label": LIVE_CHECKLIST[3], "done": True},
        {"key": "acknowledge", "label": LIVE_CHECKLIST[4], "done": bool(state.live_trading_confirmed)},
    ]
    return {
        "env_flag_enabled": settings.live_trading_enabled,
        "confirmed": bool(state.live_trading_confirmed),
        "ready": all(item["done"] for item in items) and settings.live_trading_enabled,
        "items": items,
        "warning": (
            "Live trading uses real money. Start with a small balance and with the Binance "
            "testnet. This software gives no profit guarantee."
        ),
    }


@router.post("/live/confirm", response_model=MessageResponse, summary="Enable live trading")
async def confirm_live(
    payload: LiveTradingRequest, db: DbSession, context: Context
) -> MessageResponse:
    settings = get_settings()
    if payload.confirmed:
        if not settings.live_trading_enabled:
            raise HTTPException(
                status_code=403,
                detail=(
                    "LIVE_TRADING_ENABLED is false in the .env file. Set it to true and "
                    "restart the backend before enabling live trading."
                ),
            )
        if not (payload.acknowledge_risk and payload.acknowledge_no_profit_guarantee):
            raise HTTPException(
                status_code=400,
                detail="Both risk acknowledgements are required to enable live trading.",
            )
        credentials = credentials_service.resolve_credentials(db)
        if not credentials.is_present:
            raise HTTPException(status_code=400, detail="Store your API credentials first.")

    bot_state_service.confirm_live_trading(db, payload.confirmed)
    config = settings_service.get_trading_config(db)
    config.mode = TradingMode.LIVE if payload.confirmed else TradingMode.PAPER
    settings_service.save_trading_config(db, config)
    await context.rebuild(db)

    return MessageResponse(
        message=(
            "Live trading enabled. Real orders can now be sent."
            if payload.confirmed
            else "Live trading disabled. The platform is back in paper mode."
        )
    )


@router.post("/paper/reset", response_model=MessageResponse, summary="Reset the paper account")
def reset_paper(payload: PaperResetRequest, db: DbSession) -> MessageResponse:
    portfolio = PortfolioEngine(TradingMode.PAPER)
    open_positions = portfolio.open_positions(db)
    if open_positions:
        raise HTTPException(
            status_code=409,
            detail="Close every open paper position before resetting the account.",
        )
    portfolio.set_balance(db, payload.starting_balance)
    removed = 0
    if payload.clear_history:
        removed += db.query(Trade).filter(Trade.mode == TradingMode.PAPER.value).delete()
        db.query(Order).filter(Order.mode == TradingMode.PAPER.value).delete()
        db.query(Signal).filter(Signal.mode == TradingMode.PAPER.value).delete()
        db.query(Position).filter(Position.mode == TradingMode.PAPER.value).delete()
        db.commit()
    event_service.log_event(
        db,
        message=f"Paper account reset to {payload.starting_balance}",
        category="paper_trading",
        severity=EventSeverity.WARNING,
        mode=TradingMode.PAPER.value,
    )
    return MessageResponse(
        message="Paper account reset.", details={"removed_trades": removed}
    )
