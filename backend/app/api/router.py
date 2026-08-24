"""Root API router."""

from fastapi import APIRouter

from app.api.routes import (
    backtests,
    dashboard,
    exchange,
    market_data,
    positions,
    risk,
    settings,
    strategies,
    system,
    trades,
    trading,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(dashboard.router)
api_router.include_router(positions.router)
api_router.include_router(trades.router)
api_router.include_router(strategies.router)
api_router.include_router(backtests.router)
api_router.include_router(risk.router)
api_router.include_router(settings.router)
api_router.include_router(exchange.router)
api_router.include_router(trading.router)
api_router.include_router(market_data.router)
