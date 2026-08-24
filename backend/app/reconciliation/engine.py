"""Reconciliation Engine.

Compares the local database with the exchange. Any disagreement about money
or positions is treated as a critical fault: the platform stops opening new
trades until a human looks at it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import (
    EventSeverity,
    PositionSide,
    ReconciliationStatus,
    TradingMode,
)
from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.exchange.base import ExchangeGateway
from app.portfolio.engine import PortfolioEngine
from app.services.bot_state_service import set_reconciliation
from app.services.event_service import log_event

logger = get_logger(__name__)

QUANTITY_TOLERANCE = 1e-8
BALANCE_TOLERANCE_PCT = 1.0


@dataclass(slots=True)
class Difference:
    """One disagreement between the local state and the exchange."""

    kind: str
    symbol: str
    local: Any
    exchange: Any
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "local": self.local,
            "exchange": self.exchange,
            "message": self.message,
        }


@dataclass(slots=True)
class ReconciliationReport:
    """Outcome of one reconciliation pass."""

    status: ReconciliationStatus = ReconciliationStatus.NEVER_RUN
    checked_at: datetime = field(default_factory=utcnow)
    differences: list[Difference] = field(default_factory=list)
    local_positions: list[dict[str, Any]] = field(default_factory=list)
    exchange_positions: list[dict[str, Any]] = field(default_factory=list)
    local_balance: float | None = None
    exchange_balance: float | None = None
    open_orders: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == ReconciliationStatus.IN_SYNC

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checked_at": self.checked_at.isoformat(),
            "ok": self.ok,
            "differences": [difference.to_dict() for difference in self.differences],
            "local_positions": self.local_positions,
            "exchange_positions": self.exchange_positions,
            "local_balance": self.local_balance,
            "exchange_balance": self.exchange_balance,
            "open_orders": self.open_orders,
            "error": self.error,
        }


class ReconciliationEngine:
    """Keeps the local truth and the exchange truth honest with each other."""

    def __init__(
        self,
        gateway: ExchangeGateway,
        portfolio: PortfolioEngine,
        mode: TradingMode = TradingMode.PAPER,
    ) -> None:
        self.gateway = gateway
        self.portfolio = portfolio
        self.mode = mode

    async def reconcile(
        self, db: Session, symbols: list[str] | None = None
    ) -> ReconciliationReport:
        """Run a full comparison and persist the verdict."""
        report = ReconciliationReport(checked_at=utcnow())
        try:
            exchange_positions = await self.gateway.fetch_positions(symbols)
            balance = await self.gateway.fetch_balance()
            try:
                open_orders = await self.gateway.fetch_open_orders()
            except Exception:  # pragma: no cover - not fatal for reconciliation
                open_orders = []
        except Exception as exc:
            report.status = ReconciliationStatus.ERROR
            report.error = str(exc)[:500]
            set_reconciliation(db, ReconciliationStatus.ERROR, report.to_dict())
            log_event(
                db,
                message=f"Reconciliation could not reach the exchange: {exc}",
                category="reconciliation",
                severity=EventSeverity.ERROR,
                mode=self.mode.value,
            )
            return report

        local_positions = self.portfolio.open_positions(db)
        report.local_positions = [
            {
                "symbol": position.symbol,
                "side": position.side,
                "quantity": float(position.quantity),
                "entry_price": float(position.entry_price),
            }
            for position in local_positions
        ]
        report.exchange_positions = [
            {
                "symbol": position.symbol,
                "side": position.side.value,
                "quantity": float(position.quantity),
                "entry_price": float(position.entry_price),
            }
            for position in exchange_positions
        ]
        report.exchange_balance = float(balance.total)
        report.local_balance = float(self.portfolio.balance(db))
        report.open_orders = len(open_orders)

        report.differences = self._compare_positions(report.local_positions, exchange_positions)
        if self.mode == TradingMode.LIVE:
            report.differences.extend(
                self._compare_balance(report.local_balance, report.exchange_balance)
            )

        report.status = (
            ReconciliationStatus.IN_SYNC
            if not report.differences
            else ReconciliationStatus.MISMATCH
        )
        set_reconciliation(db, report.status, report.to_dict())

        if report.differences:
            log_event(
                db,
                message="Reconciliation mismatch: new trades are blocked",
                category="reconciliation",
                severity=EventSeverity.CRITICAL,
                details={"differences": [d.to_dict() for d in report.differences]},
                mode=self.mode.value,
            )
        else:
            logger.info("Reconciliation clean", extra={"mode": self.mode.value})
        return report

    # -- comparisons --------------------------------------------------------
    @staticmethod
    def _compare_positions(
        local_positions: list[dict[str, Any]], exchange_positions: list
    ) -> list[Difference]:
        """Every symbol must agree on side and quantity."""
        differences: list[Difference] = []
        local_map = {item["symbol"].upper(): item for item in local_positions}
        exchange_map = {
            position.symbol.upper(): position
            for position in exchange_positions
            if position.quantity > 0
        }

        for symbol in sorted(set(local_map) | set(exchange_map)):
            local = local_map.get(symbol)
            remote = exchange_map.get(symbol)
            if local and not remote:
                differences.append(
                    Difference(
                        kind="position_missing_on_exchange",
                        symbol=symbol,
                        local=local["quantity"],
                        exchange=0.0,
                        message=(
                            f"Local database holds {local['side']} {local['quantity']} {symbol} "
                            "but the exchange reports no position"
                        ),
                    )
                )
            elif remote and not local:
                differences.append(
                    Difference(
                        kind="position_missing_locally",
                        symbol=symbol,
                        local=0.0,
                        exchange=float(remote.quantity),
                        message=(
                            f"Exchange holds {remote.side.value} {remote.quantity} {symbol} "
                            "which is unknown to this platform"
                        ),
                    )
                )
            elif local and remote:
                if abs(float(local["quantity"]) - float(remote.quantity)) > QUANTITY_TOLERANCE:
                    differences.append(
                        Difference(
                            kind="quantity_mismatch",
                            symbol=symbol,
                            local=float(local["quantity"]),
                            exchange=float(remote.quantity),
                            message=(
                                f"{symbol} size differs: local {local['quantity']} vs exchange "
                                f"{remote.quantity}"
                            ),
                        )
                    )
                local_side = str(local["side"]).upper()
                remote_side = (
                    remote.side.value if isinstance(remote.side, PositionSide) else str(remote.side)
                )
                if local_side != str(remote_side).upper():
                    differences.append(
                        Difference(
                            kind="side_mismatch",
                            symbol=symbol,
                            local=local_side,
                            exchange=remote_side,
                            message=f"{symbol} direction differs: {local_side} vs {remote_side}",
                        )
                    )
        return differences

    @staticmethod
    def _compare_balance(
        local_balance: float | None, exchange_balance: float | None
    ) -> list[Difference]:
        """Balances may drift slightly, large gaps are a problem."""
        if local_balance is None or exchange_balance is None:
            return []
        if exchange_balance <= 0:
            return []
        deviation = abs(local_balance - exchange_balance) / exchange_balance * 100.0
        if deviation <= BALANCE_TOLERANCE_PCT:
            return []
        return [
            Difference(
                kind="balance_mismatch",
                symbol="",
                local=local_balance,
                exchange=exchange_balance,
                message=(
                    f"Balance differs by {deviation:.2f} percent "
                    f"(local {local_balance:.2f}, exchange {exchange_balance:.2f})"
                ),
            )
        ]
