"""Gold and the FX majors: routing, guards and the traps they carry."""

from __future__ import annotations

from datetime import UTC

import pytest

from app.core.constants import OrderType, RiskRejectionCode
from app.exchange.filters import default_filters_for
from app.execution.validators import validate_order
from app.market_data import reference_markets
from app.market_data.providers.yahoo import (
    INTERVALS,
    MAX_RANGE_DAYS,
    YahooHistoryProvider,
    max_history_days,
    supports,
)
from app.market_data.reference_markets import MarketKind


class TestRegistry:
    def test_the_three_requested_markets_exist(self) -> None:
        for symbol in ("XAU/USDT", "EUR/USD", "USD/JPY"):
            assert reference_markets.get(symbol) is not None

    def test_an_ordinary_crypto_symbol_is_not_a_reference_market(self) -> None:
        assert reference_markets.get("BTC/USDT") is None
        assert reference_markets.kind_of("BTC/USDT") is MarketKind.CRYPTO

    def test_gold_is_tradable_because_binance_lists_it(self) -> None:
        assert reference_markets.is_tradable("XAU/USDT") is True
        assert reference_markets.get("XAU/USDT").provider == "binance"

    def test_forex_is_not_tradable(self) -> None:
        """Binance has no FX market, so an order could never be filled."""
        assert reference_markets.is_tradable("EUR/USD") is False
        assert reference_markets.is_tradable("USD/JPY") is False

    def test_unknown_symbols_default_to_tradable(self) -> None:
        """Only the registry may switch trading off; a new coin is not blocked."""
        assert reference_markets.is_tradable("SOMETHING/USDT") is True

    def test_externally_sourced_excludes_binance_backed_markets(self) -> None:
        external = reference_markets.externally_sourced()
        assert set(external) == {"EUR/USD", "USD/JPY"}


class TestTradingGuards:
    """A research-only market must not be able to reach the exchange."""

    def test_the_order_validator_refuses_forex(self) -> None:
        result = validate_order(
            symbol="EUR/USD",
            quantity=1000.0,
            price=1.10,
            stop_price=None,
            order_type=OrderType.LIMIT,
            filters=default_filters_for("EUR/USD"),
        )
        assert result.valid is False
        assert any("research-only" in error for error in result.errors)

    def test_the_order_validator_allows_gold(self) -> None:
        result = validate_order(
            symbol="XAU/USDT",
            quantity=1.0,
            price=4000.0,
            stop_price=None,
            order_type=OrderType.LIMIT,
            filters=default_filters_for("XAU/USDT"),
        )
        assert result.valid is True

    def test_a_rejection_code_exists_for_it(self) -> None:
        assert RiskRejectionCode.SYMBOL_NOT_TRADABLE.value == "SYMBOL_NOT_TRADABLE"


class TestSessionGaps:
    def test_forex_is_marked_as_having_session_gaps(self) -> None:
        """A week of FX contains five sessions, so short pages are normal."""
        assert reference_markets.has_session_gaps("EUR/USD") is True

    def test_crypto_has_no_session_gaps(self) -> None:
        assert reference_markets.has_session_gaps("BTC/USDT") is False
        assert reference_markets.has_session_gaps("XAU/USDT") is False


class TestVolumeTrap:
    def test_forex_feeds_carry_no_volume(self) -> None:
        assert reference_markets.has_volume("EUR/USD") is False

    def test_the_gated_strategy_is_named_as_untestable(self) -> None:
        """Zero trades from a volume-gated strategy is not a result.

        Spot FX has no consolidated volume, so a hard volume filter can never
        pass. Reporting that as "no signals" would read as a working strategy
        finding nothing, when it never ran at all.
        """
        untestable = reference_markets.untestable_strategies("EUR/USD")
        assert untestable == ("vwap_pullback",)

    def test_strategies_that_merely_score_volume_are_listed_separately(self) -> None:
        """Six strategies mention volume; only one is gated on it.

        The rest use it as one score component and still trade, so calling them
        untestable would throw away results that are perfectly readable.
        """
        degraded = reference_markets.degraded_strategies("EUR/USD")
        assert "adaptive_momentum" in degraded
        assert "vwap_pullback" not in degraded
        assert "trend_following" not in degraded

    def test_neither_list_applies_to_a_market_with_volume(self) -> None:
        assert reference_markets.degraded_strategies("XAU/USDT") == ()

    def test_markets_with_volume_have_no_untestable_strategies(self) -> None:
        assert reference_markets.untestable_strategies("XAU/USDT") == ()
        assert reference_markets.untestable_strategies("BTC/USDT") == ()


class TestYahooProvider:
    def test_only_the_intervals_yahoo_really_has_are_offered(self) -> None:
        """Yahoo has no 2h, 6h, 8h or 12h bar; claiming otherwise would return
        the wrong resolution silently."""
        assert supports("1h") and supports("1d")
        assert not supports("2h")
        assert not supports("4h")

    def test_history_limits_are_recorded(self) -> None:
        """Asking for a year of 15 minute FX candles returns 60 days without
        complaining, so the limit has to be known before the request."""
        assert max_history_days("15m") == 60
        assert max_history_days("1h") == 730
        assert set(MAX_RANGE_DAYS) == set(INTERVALS)

    def test_rejects_an_interval_it_cannot_serve(self) -> None:
        import asyncio

        provider = YahooHistoryProvider()
        with pytest.raises(ValueError, match="no 4h bar"):
            asyncio.run(provider.fetch_ohlcv("EUR/USD", "4h"))

    def test_parses_a_chart_payload(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1_700_000_000, 1_700_003_600],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [1.05, 1.06],
                                    "high": [1.07, 1.08],
                                    "low": [1.04, 1.05],
                                    "close": [1.06, 1.07],
                                    "volume": [0, 0],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        rows = YahooHistoryProvider._parse(payload)
        assert len(rows) == 2
        assert rows[0][0] == 1_700_000_000_000  # milliseconds
        assert rows[0][4] == pytest.approx(1.06)

    def test_null_padded_closed_sessions_are_dropped(self) -> None:
        """Yahoo pads closed sessions with nulls. Carried through they become
        flat zero-range bars that quietly break ATR and every range indicator."""
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1, 2, 3],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [1.0, None, 1.2],
                                    "high": [1.1, None, 1.3],
                                    "low": [0.9, None, 1.1],
                                    "close": [1.05, None, 1.25],
                                    "volume": [0, None, 0],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        rows = YahooHistoryProvider._parse(payload)
        assert len(rows) == 2

    def test_an_empty_result_is_not_an_error(self) -> None:
        assert YahooHistoryProvider._parse({"chart": {"result": []}}) == []

    def test_an_api_error_is_raised(self) -> None:
        with pytest.raises(RuntimeError):
            YahooHistoryProvider._parse({"chart": {"error": {"code": "Not Found"}}})


class TestZeroVolumeDoesNotCrashStrategies:
    """A feed with no volume must degrade, not explode.

    ``adaptive_momentum`` blanked a zero volume average with ``pd.NA`` and then
    cast the column back to float64. On a normal market at most a few bars are
    blanked and the cast succeeds. On spot FX every bar is blanked, the column
    becomes entirely NA, and the cast raised TypeError - taking down the whole
    backtest rather than simply scoring no volume.
    """

    def _flat_volume_frame(self):
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(7)
        n = 1500
        close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.006, n)))
        return pd.DataFrame(
            {
                "open_time": [1_600_000_000_000 + i * 3_600_000 for i in range(n)],
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": 0.0,
            }
        )

    def test_every_strategy_survives_a_zero_volume_feed(self) -> None:
        from datetime import datetime, timedelta

        from app.backtesting.engine import BacktestEngine, BacktestRequest
        from app.exchange.filters import default_filters_for
        from app.strategies.registry import available_keys, create_strategy

        frame = self._flat_volume_frame()
        engine = BacktestEngine()
        origin = datetime(2020, 1, 1, tzinfo=UTC)
        request_start = origin + timedelta(hours=900)
        request_end = origin + timedelta(hours=len(frame))

        for key in available_keys():
            request = BacktestRequest(
                strategy_key=key,
                symbol="T/USDT",
                timeframe="1h",
                start=request_start,
                end=request_end,
            )
            engine.run(frame, request, default_filters_for("T/USDT"), create_strategy(key))
