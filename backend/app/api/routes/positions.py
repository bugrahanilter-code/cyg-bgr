"""Open position endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Context, DbSession
from app.core.constants import ExitReason, TradingMode
from app.core.exceptions import TradingPlatformError
from app.models.trading import Position
from app.schemas.common import MessageResponse
from app.schemas.requests import ClosePositionRequest
from app.services import bot_state_service
from app.services.dashboard_service import open_positions_payload

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", summary="Open positions with live prices")
def list_positions(
    db: DbSession, context: Context, mode: str | None = None
) -> list[dict[str, Any]]:
    state = bot_state_service.get_state(db)
    trading_mode = TradingMode(mode) if mode else TradingMode(state.mode)

    def price_lookup(symbol: str):
        return context.market_data.last_price(symbol) if context.market_data else None

    return open_positions_payload(db, trading_mode, price_lookup)


@router.post(
    "/{position_id}/close",
    response_model=MessageResponse,
    summary="Close one position at market",
)
async def close_position(
    position_id: int, payload: ClosePositionRequest, db: DbSession, context: Context
) -> MessageResponse:
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != "OPEN":
        raise HTTPException(status_code=409, detail="Position is not open")
    if context.engine is None:
        raise HTTPException(status_code=503, detail="Trading engine is not available")

    price = context.market_data.last_price(position.symbol) if context.market_data else None
    open_quantity = float(position.quantity)
    partial = payload.percent < 100.0
    quantity = open_quantity * payload.percent / 100.0 if partial else None

    try:
        trade = await context.engine.execution.execute_exit(
            db,
            position,
            reason=ExitReason.MANUAL,
            price_hint=price,
            quantity=quantity,
        )
    except TradingPlatformError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if trade is None:
        return MessageResponse(
            ok=False, message="Borsa kapatma emrini onaylamadı. Pozisyon açık kaldı."
        )

    db.refresh(position)
    remaining = float(position.quantity)
    if partial and remaining > 0:
        message = (
            f"{position.symbol}: pozisyonun %{payload.percent:g}'i kapatıldı, "
            f"{remaining:g} açık kaldı."
        )
    else:
        message = f"{position.symbol} kapatıldı."

    return MessageResponse(
        message=message,
        details={
            "net_pnl": float(trade.net_pnl),
            "exit_price": float(trade.exit_price),
            "closed_quantity": float(trade.quantity),
            "remaining_quantity": remaining,
        },
    )


@router.post("/close-all", response_model=MessageResponse, summary="Close every open position")
async def close_all(db: DbSession, context: Context) -> MessageResponse:
    if context.engine is None:
        raise HTTPException(status_code=503, detail="Trading engine is not available")
    closed = await context.engine.close_all_positions(db, ExitReason.MANUAL)
    return MessageResponse(message=f"{closed} position(s) closed.")
