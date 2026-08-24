"""Automatic rotation into the top 24 hour movers, and strategy selection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import Context, DbSession
from app.schemas.common import MessageResponse
from app.services import event_service, rotation_service, settings_service
from app.services.rotation_service import RotationConfig
from app.services.strategy_selection import SelectionCriteria, build_validation_plan, select_best

router = APIRouter(prefix="/rotation", tags=["rotation"])

CHURN_WARNING = (
    "Rotation is a selection rule, not an edge. A coin enters the list because "
    "it already rose; nothing here predicts that it continues. Every rotation "
    "also pays an exit on what leaves and an entry on what arrives, and "
    "transaction cost has beaten every strategy studied on this platform."
)


@router.get("", summary="Rotation configuration and status")
def read_rotation(db: DbSession) -> dict[str, Any]:
    config = rotation_service.get_config(db)
    runs = rotation_service.history(db, limit=10)
    trading = settings_service.get_trading_config(db)
    return {
        "config": config.model_dump(),
        "defaults": RotationConfig().model_dump(),
        "enabled_symbols": trading.enabled_symbols,
        "last_run": rotation_service.run_to_dict(runs[0]) if runs else None,
        "history": [rotation_service.run_to_dict(run) for run in runs],
        "warning": CHURN_WARNING,
    }


@router.put("", response_model=MessageResponse, summary="Update the rotation setup")
def update_rotation(payload: RotationConfig, db: DbSession) -> MessageResponse:
    before = rotation_service.get_config(db).model_dump()
    rotation_service.save_config(db, payload)
    event_service.audit(
        db,
        action="update_rotation_config",
        entity="rotation_config",
        before=before,
        after=payload.model_dump(),
    )
    detail = "Rotation is ON." if payload.enabled else "Rotation is OFF."
    if payload.enabled and payload.dry_run:
        detail += " Dry run: it will report what it would change without changing it."
    return MessageResponse(
        message=f"{detail} Refreshing every {payload.interval_minutes} minutes, "
        f"top {payload.top_n} by 24h change.",
        details={"config": payload.model_dump(), "warning": CHURN_WARNING},
    )


@router.post("/preview", summary="What rotation would do right now")
async def preview(db: DbSession, context: Context) -> dict[str, Any]:
    """Rank and plan without touching the enabled set."""
    from app.services import universe_service

    config = rotation_service.get_config(db)
    try:
        snapshot = await universe_service.load_universe(context, with_context=False)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Binance: {exc}") from exc
    plan = rotation_service.plan_rotation(db, snapshot["rows"], config)
    plan["config"] = config.model_dump()
    plan["warning"] = CHURN_WARNING
    return plan


@router.post("/run", summary="Run a rotation now")
async def run_now(db: DbSession, context: Context, dry_run: bool | None = None) -> dict[str, Any]:
    record = await rotation_service.run_rotation(
        context, db, triggered_by="manual", force_dry_run=dry_run
    )
    payload = rotation_service.run_to_dict(record)
    payload["warning"] = CHURN_WARNING
    return payload


@router.get("/history", summary="Past rotations")
def rotation_history(
    db: DbSession, limit: int = Query(default=30, ge=1, le=200)
) -> list[dict[str, Any]]:
    return [rotation_service.run_to_dict(run) for run in rotation_service.history(db, limit)]


# ---------------------------------------------------------------------------
# Strategy selection
# ---------------------------------------------------------------------------
@router.post("/select-strategy/{sweep_id}", summary="Pick a strategy and timeframe")
def select_strategy(
    sweep_id: int, db: DbSession, criteria: SelectionCriteria | None = None
) -> dict[str, Any]:
    """Rank a sweep's combinations and return a winner, or say there is none.

    A verdict of NO_QUALIFYING_COMBINATION is a real answer, not a failure.
    """
    try:
        result = select_best(db, sweep_id, criteria)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if result["winner"]:
        trading = settings_service.get_trading_config(db)
        result["validation_plan"] = build_validation_plan(
            result["winner"], list(trading.enabled_symbols)
        )
    return result


@router.post("/apply-strategy", response_model=MessageResponse, summary="Trade one combination")
async def apply_strategy(
    payload: dict[str, Any], db: DbSession, context: Context
) -> MessageResponse:
    """Switch the engine to one strategy on one timeframe.

    Every other strategy is disabled, so the account trades exactly the
    combination that was selected rather than the selection plus whatever was
    already running.
    """
    strategy_key = str(payload.get("strategy_key") or "").strip()
    timeframe = str(payload.get("timeframe") or "").strip()
    acknowledged = bool(payload.get("acknowledge_selection_bias"))

    if not strategy_key or not timeframe:
        raise HTTPException(status_code=400, detail="strategy_key and timeframe are required")
    if not acknowledged:
        raise HTTPException(
            status_code=400,
            detail=(
                "Confirm that you understand this combination was chosen by "
                "comparing many alternatives on one window, and that its "
                "backtest number is inflated by that selection."
            ),
        )

    from app.core.constants import SUPPORTED_TIMEFRAMES
    from app.strategies.registry import available_keys

    if strategy_key not in available_keys():
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {strategy_key}")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"Unsupported timeframe: {timeframe}")

    config = settings_service.get_trading_config(db)
    before = config.model_dump(mode="json")
    config.timeframe = timeframe
    config.enabled_strategies = {key: key == strategy_key for key in available_keys()}
    settings_service.save_trading_config(db, config)
    event_service.audit(
        db,
        action="apply_selected_strategy",
        entity="trading_config",
        before=before,
        after=config.model_dump(mode="json"),
    )
    await context.rebuild(db)

    return MessageResponse(
        message=(
            f"{strategy_key} on {timeframe} is now the only enabled strategy, "
            f"trading {len(config.enabled_symbols)} markets. Live trading is "
            "unaffected and stays off until it is separately confirmed."
        ),
        details={"strategy_key": strategy_key, "timeframe": timeframe},
    )
