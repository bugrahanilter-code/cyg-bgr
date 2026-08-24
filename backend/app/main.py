"""FastAPI application entry point.

Startup order matters:

1. configure logging (with secret redaction) BEFORE anything else runs
2. create/upgrade the database schema and seed the safe defaults
3. build the application context (market data, gateways, engine)
4. the engine performs its restart recovery before it trades again
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import TradingPlatformError
from app.core.logging import configure_logging, get_logger
from app.core.time_utils import utcnow
from app.database.init_db import init_database
from app.services.container import context

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

DESCRIPTION = """
Modular cryptocurrency algorithmic trading platform.

**This software does not guarantee any profit.** Backtest results describe the
past and are not a prediction. Live trading is disabled by default and requires
an explicit two-step confirmation.

Pipeline: market data -> market regime -> strategies -> signals -> risk engine
-> portfolio -> execution engine -> exchange -> trade journal -> dashboard.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info(
        "Starting the trading platform",
        extra={"version": __version__, "env": settings.app_env},
    )
    if settings.auto_create_tables:
        init_database()
    try:
        await context.startup()
    except Exception as exc:  # pragma: no cover - startup must not crash the API
        logger.exception("Application context failed to start: %s", exc)
    yield
    await context.shutdown()
    logger.info("Trading platform stopped")


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.exception_handler(TradingPlatformError)
async def platform_error_handler(request: Request, exc: TradingPlatformError) -> JSONResponse:
    """Map domain errors onto clean HTTP responses."""
    logger.warning(
        "Domain error",
        extra={"path": str(request.url.path), "code": exc.code, "error": exc.message},
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "code": exc.code, "message": exc.message, "details": exc.details},
    )


@app.get("/health", tags=["system"], summary="Liveness probe")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "time": utcnow().isoformat() + "Z"}


@app.get("/", tags=["system"], summary="API root")
def root() -> dict[str, Any]:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "api_prefix": settings.api_prefix,
        "disclaimer": "This software does not guarantee any profit. Trade at your own risk.",
    }
