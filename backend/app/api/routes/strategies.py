"""Strategy listing, configuration and performance comparison."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import Context, DbSession
from app.core.constants import TradingMode
from app.schemas.common import MessageResponse
from app.schemas.requests import StrategyUpdateRequest
from app.schemas.responses import StrategyOut
from app.services import analytics_service, event_service, settings_service
from app.strategies.registry import (
    available_keys,
    create_strategy,
    get_strategy_class,
    strategy_metadata,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _params_key(strategy_key: str) -> str:
    return f"strategy_params:{strategy_key}"


def _current_params(db: Session, strategy_key: str) -> dict[str, Any]:
    stored = settings_service.get_json_setting(db, _params_key(strategy_key), {})
    return create_strategy(strategy_key, stored).params_dict()


@router.get("", response_model=list[StrategyOut], summary="Every strategy with its live state")
def list_strategies(db: DbSession, context: Context) -> list[StrategyOut]:
    trading_config = settings_service.get_trading_config(db)
    mode = trading_config.mode
    engine = context.engine
    result: list[StrategyOut] = []

    for meta in strategy_metadata():
        key = meta["key"]
        signals = engine.latest_signals() if engine else {}
        current_signal = None
        for signal_key, payload in signals.items():
            if not signal_key.startswith(f"{key}:"):
                continue
            if current_signal is None or payload.get("confidence", 0) >= current_signal.get(
                "confidence", 0
            ):
                current_signal = payload
        performance = analytics_service.summarise(
            analytics_service.load_trades(db, mode=mode, strategy_key=key)
        )
        result.append(
            StrategyOut(
                key=key,
                name=meta["name"],
                family=meta["family"],
                risk_level=meta["risk_level"],
                description=meta["description"],
                enabled=trading_config.is_strategy_enabled(key),
                params=_current_params(db, key),
                default_params=meta["default_params"],
                param_schema=meta["param_schema"],
                current_signal=current_signal,
                performance=performance,
            )
        )
    return result


@router.get("/comparison", summary="Strategy comparison across markets")
def comparison(db: DbSession, mode: str | None = None) -> dict[str, Any]:
    trading_config = settings_service.get_trading_config(db)
    trading_mode = TradingMode(mode) if mode else trading_config.mode
    return {
        "mode": trading_mode.value,
        "symbols": trading_config.enabled_symbols,
        "rows": analytics_service.strategy_breakdown(
            db,
            trading_mode,
            available_keys(),
            trading_config.enabled_symbols,
        ),
    }


@router.get("/{strategy_key}", response_model=StrategyOut, summary="One strategy")
def get_strategy(strategy_key: str, db: DbSession, context: Context) -> StrategyOut:
    for item in list_strategies(db, context):
        if item.key == strategy_key:
            return item
    raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_key}")


@router.put("/{strategy_key}", response_model=MessageResponse, summary="Update a strategy")
def update_strategy(
    strategy_key: str, payload: StrategyUpdateRequest, db: DbSession
) -> MessageResponse:
    get_strategy_class(strategy_key)  # raises 404 for unknown keys
    changes: dict[str, Any] = {}

    if payload.params is not None:
        strategy = create_strategy(strategy_key, payload.params)
        settings_service.set_json_setting(
            db, _params_key(strategy_key), strategy.params_dict(), "Strategy parameters"
        )
        changes["params"] = strategy.params_dict()

    if payload.enabled is not None:
        config = settings_service.get_trading_config(db)
        config.enabled_strategies[strategy_key] = payload.enabled
        settings_service.save_trading_config(db, config)
        changes["enabled"] = payload.enabled

    event_service.audit(
        db,
        action="update_strategy",
        entity="strategy",
        entity_id=strategy_key,
        after=changes,
    )
    return MessageResponse(message=f"{strategy_key} updated.", details=changes)


@router.post(
    "/{strategy_key}/reset-params",
    response_model=MessageResponse,
    summary="Restore the default parameters",
)
def reset_params(strategy_key: str, db: DbSession) -> MessageResponse:
    defaults = get_strategy_class(strategy_key).default_params()
    settings_service.set_json_setting(db, _params_key(strategy_key), defaults)
    return MessageResponse(message="Default parameters restored.", details=defaults)
