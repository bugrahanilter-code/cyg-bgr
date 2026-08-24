"""Root API router."""

from fastapi import APIRouter

from app.api.routes import (
    backtests,
    dashboard,
    exchange,
    market_data,
    markets,
    positions,
    risk,
    rotation,
    settings,
    strategies,
    sweeps,
    system,
    trades,
    trading,
    udf,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(dashboard.router)
api_router.include_router(positions.router)
api_router.include_router(trades.router)
api_router.include_router(strategies.router)
api_router.include_router(backtests.router)
api_router.include_router(risk.router)
api_router.include_router(rotation.router)
api_router.include_router(settings.router)
api_router.include_router(exchange.router)
api_router.include_router(trading.router)
api_router.include_router(market_data.router)
api_router.include_router(markets.router)
api_router.include_router(sweeps.router)
api_router.include_router(udf.router)
