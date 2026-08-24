"""Settings page endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import Context, DbSession
from app.core.config import get_settings
from app.models.market import Symbol
from app.schemas.common import MessageResponse
from app.schemas.requests import TradingConfigRequest
from app.services import credentials_service, event_service, settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", summary="All editable settings")
def read_settings(db: DbSession) -> dict[str, Any]:
    settings = get_settings()
    payload = settings_service.all_settings(db)
    payload["exchange"] = credentials_service.masked_view(db)
    payload["environment"] = {
        "app_env": settings.app_env,
        "live_trading_enabled_in_env": settings.live_trading_enabled,
        "default_timeframe": settings.default_timeframe,
        "supported_symbols": [
            row.symbol
            for row in db.execute(select(Symbol).order_by(Symbol.symbol.asc())).scalars().all()
        ]
        or settings.available_symbol_list,
        "paper_starting_balance": settings.paper_starting_balance,
    }
    return payload


@router.put("/trading", response_model=MessageResponse, summary="Update the trading setup")
async def update_trading(
    payload: TradingConfigRequest, db: DbSession, context: Context
) -> MessageResponse:
    config = settings_service.get_trading_config(db)
    before = config.model_dump(mode="json")
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(config, key, value)
    if config.enabled_symbols:
        config.enabled_symbols = [symbol.upper() for symbol in config.enabled_symbols]
    settings_service.save_trading_config(db, config)
    event_service.audit(
        db,
        action="update_trading_config",
        entity="trading_config",
        before=before,
        after=config.model_dump(mode="json"),
    )
    await context.rebuild(db)
    return MessageResponse(
        message="Trading settings saved.", details=config.model_dump(mode="json")
    )
