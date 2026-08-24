"""Response models.

Composite dashboard payloads are typed as dictionaries on purpose: they are
assembled by the service layer and change together with the UI. Everything
that a client filters or sorts on has an explicit model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SymbolOut(ORMModel):
    symbol: str
    base_asset: str
    quote_asset: str
    market_type: str
    enabled: bool
    tick_size: float
    step_size: float
    min_quantity: float
    min_notional: float
    max_leverage: int


class SignalOut(ORMModel):
    id: int
    uid: str
    symbol: str
    strategy_key: str
    timeframe: str
    mode: str
    candle_open_time: int
    signal_type: str
    confidence: float
    market_regime: str
    trend_regime: str
    volatility_regime: str
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    explanation: str = ""
    indicators: dict[str, Any] = Field(default_factory=dict)
    status: str
    rejection_codes: list[Any] = Field(default_factory=list)
    rejection_details: str = ""
    created_at: datetime


class OrderOut(ORMModel):
    id: int
    client_order_id: str
    exchange_order_id: str | None = None
    symbol: str
    mode: str
    strategy_key: str
    side: str
    order_type: str
    status: str
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    filled_quantity: float
    average_fill_price: float | None = None
    fee: float
    reduce_only: bool
    error_message: str | None = None
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    created_at: datetime


class TradeOut(ORMModel):
    id: int
    uid: str
    symbol: str
    strategy_key: str
    mode: str
    timeframe: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    leverage: float
    stop_loss: float | None = None
    take_profit: float | None = None
    notional: float
    opened_at: datetime
    closed_at: datetime
    duration_seconds: int
    gross_pnl: float
    fees: float
    funding: float
    slippage_cost: float
    net_pnl: float
    return_pct: float
    equity_after: float | None = None
    is_win: bool
    signal_confidence: float
    market_regime: str
    entry_reason: str
    exit_reason: str
    backtest_id: int | None = None


class BacktestOut(ORMModel):
    id: int
    uid: str
    name: str
    strategy_key: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    starting_capital: float
    status: str
    error_message: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float = 0.0
    candles_used: int = 0
    created_at: datetime
    completed_at: datetime | None = None


class BacktestDetailOut(BaseModel):
    backtest: BacktestOut
    metrics: dict[str, Any] = Field(default_factory=dict)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    drawdown_curve: list[dict[str, Any]] = Field(default_factory=list)
    monthly_returns: list[dict[str, Any]] = Field(default_factory=list)
    trade_distribution: dict[str, Any] = Field(default_factory=dict)
    walk_forward: dict[str, Any] | None = None
    trades: list[TradeOut] = Field(default_factory=list)


class StrategyOut(BaseModel):
    key: str
    name: str
    family: str
    risk_level: str = "medium"
    description: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    default_params: dict[str, Any] = Field(default_factory=dict)
    param_schema: dict[str, Any] = Field(default_factory=dict)
    current_signal: dict[str, Any] | None = None
    performance: dict[str, Any] = Field(default_factory=dict)


class SystemEventOut(ORMModel):
    id: int
    severity: str
    category: str
    message: str
    mode: str
    symbol: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AuditLogOut(ORMModel):
    id: int
    actor: str
    action: str
    entity: str
    entity_id: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    note: str
    created_at: datetime


class CandleOut(BaseModel):
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
