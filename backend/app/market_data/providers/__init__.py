"""Pluggable market-data providers.

The platform separates two very different jobs that are easy to conflate:

``OHLCV history``
    The candles every backtest and every strategy is computed on. This has to be
    exact, complete and reproducible, so it comes from the exchange we actually
    trade on (Binance). Using a second-hand source here would mean backtesting
    on numbers that differ from the ones the execution engine will see.

``Market context``
    24 hour statistics, technical ratings, screener columns. This is decoration
    for the market browser: useful for choosing what to trade, never an input to
    a trading decision. A third-party source is fine here.

TradingView is wired in as a *context* provider for exactly that reason. See
``tradingview.py`` for the details and the limitations.
"""

from app.market_data.providers.base import MarketContextProvider, MarketStats
from app.market_data.providers.tradingview import TradingViewProvider

__all__ = ["MarketContextProvider", "MarketStats", "TradingViewProvider"]
