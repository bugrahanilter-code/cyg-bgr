"""The market browser and the TradingView context provider."""

from __future__ import annotations

import pytest

from app.market_data.providers.base import MarketStats
from app.market_data.providers.tradingview import (
    COLUMNS,
    TradingViewProvider,
    from_tradingview_symbol,
    rating_label,
    to_tradingview_symbol,
)


class TestSymbolMapping:
    def test_perpetual_gets_the_p_suffix(self) -> None:
        assert to_tradingview_symbol("BTC/USDT", "futures") == "BINANCE:BTCUSDT.P"

    def test_spot_has_no_suffix(self) -> None:
        assert to_tradingview_symbol("BTC/USDT", "spot") == "BINANCE:BTCUSDT"

    @pytest.mark.parametrize(
        ("tv_symbol", "expected"),
        [
            ("BINANCE:BTCUSDT.P", "BTC/USDT"),
            ("BINANCE:1000PEPEUSDT.P", "1000PEPE/USDT"),
            ("BINANCE:ETHBTC", "ETH/BTC"),
            ("BINANCE:SOLUSDC", "SOL/USDC"),
        ],
    )
    def test_round_trip(self, tv_symbol: str, expected: str) -> None:
        assert from_tradingview_symbol(tv_symbol) == expected

    def test_mapping_is_reversible(self) -> None:
        for symbol in ("BTC/USDT", "1000SHIB/USDT", "AVAX/USDT"):
            assert from_tradingview_symbol(to_tradingview_symbol(symbol)) == symbol


class TestRatingLabel:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.9, "STRONG_BUY"),
            (0.3, "BUY"),
            (0.0, "NEUTRAL"),
            (-0.3, "SELL"),
            (-0.8, "STRONG_SELL"),
            (None, "UNKNOWN"),
        ],
    )
    def test_matches_the_published_bands(self, score, expected) -> None:
        assert rating_label(score) == expected


class TestScreenerParsing:
    def _row(self, name: str, **overrides) -> dict:
        values = {
            "name": name,
            "close": 100.0,
            "change": 2.5,
            "change_abs": 2.5,
            "high": 105.0,
            "low": 95.0,
            "volume": 1_000.0,
            "Recommend.All": 0.6,
            "Recommend.MA": 0.5,
            "Recommend.Other": 0.4,
            "RSI": 55.0,
            "ATR": 4.0,
            "relative_volume_10d_calc": 1.2,
            "Volatility.D": 3.0,
            "average_volume_10d_calc": 900.0,
        }
        values.update(overrides)
        return {"s": "BINANCE:" + name, "d": [values[column] for column in COLUMNS]}

    def test_parses_a_perpetual_row(self) -> None:
        provider = TradingViewProvider(market_type="futures")
        stats = provider._parse_row(self._row("BTCUSDT.P"))
        assert isinstance(stats, MarketStats)
        assert stats.symbol == "BTC/USDT"
        assert stats.extra["tv_rating_label"] == "STRONG_BUY"
        assert stats.extra["tv_rsi"] == 55.0

    def test_spot_rows_are_dropped_when_trading_perpetuals(self) -> None:
        """A spot pair must never overwrite the perpetual row of the same coin.

        Both are called BTCUSDT on TradingView and they have different prices,
        funding and liquidity, so mixing them would silently show the wrong
        market.
        """
        provider = TradingViewProvider(market_type="futures")
        assert provider._parse_row(self._row("BTCUSDT")) is None

    def test_short_rows_are_ignored(self) -> None:
        provider = TradingViewProvider()
        assert provider._parse_row({"s": "BINANCE:BTCUSDT.P", "d": [1, 2]}) is None

    def test_non_numeric_values_become_none(self) -> None:
        provider = TradingViewProvider(market_type="futures")
        stats = provider._parse_row(self._row("BTCUSDT.P", RSI=None, ATR="n/a"))
        assert stats is not None
        assert stats.extra["tv_rsi"] is None
        assert stats.extra["tv_atr"] is None


@pytest.mark.asyncio
class TestProviderFailureIsNotFatal:
    async def test_unreachable_screener_returns_empty_context(self, monkeypatch) -> None:
        """Context is decoration: losing it must never break the market browser."""
        provider = TradingViewProvider()

        async def boom() -> dict:
            raise RuntimeError("network down")

        monkeypatch.setattr(provider, "_scan_all", boom)
        result = await provider.fetch_context()
        assert result == {}
        assert provider.last_error is not None
        assert "network down" in provider.last_error
