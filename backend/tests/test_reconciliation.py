"""Reconciliation and restart recovery tests."""

from __future__ import annotations

from app.core.constants import (
    PositionSide,
    ReconciliationStatus,
    TradingMode,
)
from app.exchange.base import ExchangePosition
from app.portfolio.engine import PortfolioEngine
from app.reconciliation.engine import ReconciliationEngine
from app.services import bot_state_service
from tests.mocks import MockGateway


def _portfolio(db) -> PortfolioEngine:
    portfolio = PortfolioEngine(TradingMode.LIVE)
    for position in portfolio.open_positions(db):
        position.status = "CLOSED"
    db.commit()
    return portfolio


async def test_clean_state_is_in_sync(db) -> None:
    gateway = MockGateway()
    portfolio = _portfolio(db)
    engine = ReconciliationEngine(gateway, portfolio, TradingMode.LIVE)
    portfolio_balance = portfolio.balance(db)
    gateway.balance = portfolio_balance
    report = await engine.reconcile(db, ["BTC/USDT"])
    assert report.status == ReconciliationStatus.IN_SYNC
    assert report.ok


async def test_position_missing_on_exchange_is_a_mismatch(db) -> None:
    gateway = MockGateway()
    portfolio = _portfolio(db)
    gateway.balance = portfolio.balance(db)
    portfolio.create_position(
        db,
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        quantity=0.02,
        entry_price=30_000.0,
        stop_loss=29_000.0,
        take_profit=32_000.0,
        leverage=2.0,
        margin=300.0,
        strategy_key="trend_following",
    )
    engine = ReconciliationEngine(gateway, portfolio, TradingMode.LIVE)
    report = await engine.reconcile(db, ["BTC/USDT"])
    assert report.status == ReconciliationStatus.MISMATCH
    assert any(d.kind == "position_missing_on_exchange" for d in report.differences)

    state = bot_state_service.get_state(db)
    assert state.reconciliation_status == ReconciliationStatus.MISMATCH.value

    for position in portfolio.open_positions(db):
        position.status = "CLOSED"
    db.commit()


async def test_unknown_exchange_position_is_a_mismatch(db) -> None:
    gateway = MockGateway()
    portfolio = _portfolio(db)
    gateway.balance = portfolio.balance(db)
    gateway.positions.append(
        ExchangePosition(
            symbol="ETH/USDT",
            side=PositionSide.SHORT,
            quantity=1.5,
            entry_price=2_000.0,
        )
    )
    engine = ReconciliationEngine(gateway, portfolio, TradingMode.LIVE)
    report = await engine.reconcile(db, ["ETH/USDT"])
    assert report.status == ReconciliationStatus.MISMATCH
    assert any(d.kind == "position_missing_locally" for d in report.differences)


async def test_exchange_error_is_reported(db) -> None:
    class BrokenGateway(MockGateway):
        async def fetch_positions(self, symbols=None):
            raise RuntimeError("network down")

    engine = ReconciliationEngine(BrokenGateway(), _portfolio(db), TradingMode.LIVE)
    report = await engine.reconcile(db, ["BTC/USDT"])
    assert report.status == ReconciliationStatus.ERROR
    assert not report.ok
