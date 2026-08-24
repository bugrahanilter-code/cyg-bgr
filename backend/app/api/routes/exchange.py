"""Binance connection management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import Context, DbSession
from app.models.market import Symbol
from app.schemas.common import MessageResponse
from app.schemas.requests import CredentialsRequest
from app.schemas.responses import SymbolOut
from app.services import credentials_service, event_service

router = APIRouter(prefix="/exchange", tags=["exchange"])

WITHDRAWAL_WARNING = (
    "Create the API key with reading (and futures, if needed) permission only. "
    "The withdrawal permission must stay DISABLED. This platform never calls a "
    "withdrawal endpoint."
)


@router.get("/status", summary="Connection status and masked credentials")
def status(db: DbSession, context: Context) -> dict[str, Any]:
    view = credentials_service.masked_view(db)
    view["connection_status"] = context.exchange_status.value
    view["connection_error"] = context.exchange_error
    view["gateway"] = context.trading_gateway.name if context.trading_gateway else "none"
    view["security_notice"] = WITHDRAWAL_WARNING
    return view


@router.post("/credentials", response_model=MessageResponse, summary="Store API credentials")
async def save_credentials(
    payload: CredentialsRequest, db: DbSession, context: Context
) -> MessageResponse:
    if not payload.withdrawal_disabled_confirmed:
        raise HTTPException(
            status_code=400,
            detail=(
                "Please confirm that the withdrawal permission is disabled on this API key "
                "before saving it."
            ),
        )
    try:
        credentials_service.save_credentials(
            db,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            market_type=payload.market_type,
            testnet=payload.testnet,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    event_service.audit(db, action="save_api_credentials", entity="api_credential")
    await context.rebuild(db)
    result = await context.test_exchange_connection(db)
    return MessageResponse(
        message="API credentials saved. " + result.get("message", ""),
        details={"test": result, "security_notice": WITHDRAWAL_WARNING},
    )


@router.delete("/credentials", response_model=MessageResponse, summary="Delete API credentials")
async def delete_credentials(db: DbSession, context: Context) -> MessageResponse:
    removed = credentials_service.delete_credentials(db)
    event_service.audit(db, action="delete_api_credentials", entity="api_credential")
    await context.rebuild(db)
    return MessageResponse(message=f"{removed} credential record(s) deleted.")


@router.post("/test", summary="Test the Binance connection")
async def test_connection(db: DbSession, context: Context) -> dict[str, Any]:
    result = await context.test_exchange_connection(db)
    result["security_notice"] = WITHDRAWAL_WARNING
    return result


@router.post("/refresh-filters", summary="Download the exchange trading rules")
async def refresh_filters(db: DbSession, context: Context) -> dict[str, Any]:
    return await context.refresh_symbol_filters(db)


@router.get("/symbols", response_model=list[SymbolOut], summary="Known markets")
def symbols(db: DbSession) -> list[SymbolOut]:
    rows = db.execute(select(Symbol).order_by(Symbol.symbol.asc())).scalars().all()
    return [SymbolOut.model_validate(row) for row in rows]


@router.get("/top-symbols", summary="Highest volume crypto markets on Binance")
async def top_symbols(context: Context, limit: int = 10) -> dict[str, Any]:
    """Live ranking by 24 hour quote volume.

    Tokenised stocks and commodities are excluded and each coin appears once.
    """
    try:
        rows = await context.discover_top_symbols(min(max(limit, 1), 50))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Binance: {exc}") from exc
    return {
        "symbols": rows,
        "note": (
            "Tokenised stocks and commodities are filtered out because they do not "
            "trade around the clock. Each coin is listed once."
        ),
    }


@router.post("/symbols/sync-top", summary="Add the highest volume markets")
async def sync_top_symbols(db: DbSession, context: Context, limit: int = 10) -> dict[str, Any]:
    """Add the top markets to the symbol list without enabling them for trading."""
    try:
        result = await context.sync_top_symbols(db, min(max(limit, 1), 50))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Binance: {exc}") from exc
    event_service.audit(
        db,
        action="sync_top_symbols",
        entity="symbol",
        after={"added": result["added"], "updated": result["updated"]},
    )
    result["message"] = (
        f"{len(result['added'])} market(s) added, {len(result['updated'])} updated. "
        "Enable the ones you want to trade in Settings."
    )
    return result
