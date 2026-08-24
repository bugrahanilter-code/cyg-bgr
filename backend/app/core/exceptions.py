"""Typed exceptions used across the platform."""

from __future__ import annotations


class TradingPlatformError(Exception):
    """Base class for every error raised by this application."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(TradingPlatformError):
    status_code = 400
    code = "configuration_error"


class ExchangeError(TradingPlatformError):
    status_code = 502
    code = "exchange_error"


class ExchangeAuthError(ExchangeError):
    status_code = 401
    code = "exchange_auth_error"


class ExchangeConnectionError(ExchangeError):
    status_code = 503
    code = "exchange_connection_error"


class InsufficientDataError(TradingPlatformError):
    status_code = 422
    code = "insufficient_data"


class StaleMarketDataError(TradingPlatformError):
    status_code = 503
    code = "stale_market_data"


class RiskRejectedError(TradingPlatformError):
    status_code = 409
    code = "risk_rejected"


class OrderValidationError(TradingPlatformError):
    status_code = 400
    code = "order_validation_error"


class ExecutionError(TradingPlatformError):
    status_code = 502
    code = "execution_error"


class ReconciliationError(TradingPlatformError):
    status_code = 409
    code = "reconciliation_error"


class LiveTradingDisabledError(TradingPlatformError):
    status_code = 403
    code = "live_trading_disabled"


class StrategyError(TradingPlatformError):
    status_code = 400
    code = "strategy_error"


class NotFoundError(TradingPlatformError):
    status_code = 404
    code = "not_found"
