"""The candle cache must not re-download what it already holds."""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.constants import timeframe_to_ms
from app.market_data import store
from app.market_data.service import MarketDataService

STEP = timeframe_to_ms("1h")
START = 1_700_000_000_000 - (1_700_000_000_000 % STEP)


def _frame(count: int, start_ms: int = START) -> pd.DataFrame:
    times = [start_ms + index * STEP for index in range(count)]
    return pd.DataFrame(
        {
            "open_time": times,
            "open": [100.0] * count,
            "high": [101.0] * count,
            "low": [99.0] * count,
            "close": [100.5] * count,
            "volume": [10.0] * count,
        }
    )


class _RecordingGateway:
    """Counts fetches so the test can prove a download was skipped."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def fetch_ohlcv(self, symbol, timeframe, since_ms=None, limit=500):
        self.calls.append(since_ms or 0)
        return []


@pytest.fixture
def service() -> MarketDataService:
    gateway = _RecordingGateway()
    instance = MarketDataService.__new__(MarketDataService)
    instance.gateway = gateway  # type: ignore[attr-defined]
    return instance


class TestRangeCoverage:
    def test_reports_nothing_for_an_empty_cache(self, db) -> None:
        count, first, last = store.range_coverage(db, "NEW/USDT", "1h", START, START + 100 * STEP)
        assert (count, first, last) == (0, None, None)

    def test_reports_the_stored_window(self, db) -> None:
        store.save_candles(db, "COV/USDT", "1h", _frame(50))
        count, first, last = store.range_coverage(db, "COV/USDT", "1h", START, START + 49 * STEP)
        assert count == 50
        assert first == START
        assert last == START + 49 * STEP

    def test_ignores_candles_outside_the_window(self, db) -> None:
        store.save_candles(db, "OUT/USDT", "1h", _frame(50))
        count, _, _ = store.range_coverage(db, "OUT/USDT", "1h", START, START + 9 * STEP)
        assert count == 10


@pytest.mark.asyncio
class TestDownloadSkipsCachedRanges:
    async def test_a_fully_cached_range_is_not_downloaded_again(self, db, service) -> None:
        """This is what makes a second sweep over the same grid cheap."""
        store.save_candles(db, "CACHED/USDT", "1h", _frame(200))
        end_ms = START + 199 * STEP

        stored = await service.download_range("CACHED/USDT", "1h", START, end_ms, db=db)

        assert stored == 0
        assert service.gateway.calls == []

    async def test_a_partial_range_resumes_instead_of_restarting(self, db, service) -> None:
        store.save_candles(db, "PARTIAL/USDT", "1h", _frame(100))
        end_ms = START + 199 * STEP

        await service.download_range("PARTIAL/USDT", "1h", START, end_ms, db=db)

        assert service.gateway.calls, "a partial range must still be downloaded"
        # It resumes just after the last cached candle rather than at the start.
        assert service.gateway.calls[0] == START + 100 * STEP

    async def test_an_empty_cache_downloads_from_the_beginning(self, db, service) -> None:
        await service.download_range("EMPTY/USDT", "1h", START, START + 199 * STEP, db=db)
        assert service.gateway.calls[0] == START

    async def test_a_gap_before_the_start_forces_a_full_download(self, db, service) -> None:
        """Cached candles that do not reach the start cannot be resumed from.

        Resuming would silently leave the beginning of the window missing, and
        a backtest would then run on a shorter period than it was asked for.
        """
        store.save_candles(db, "GAP/USDT", "1h", _frame(50, start_ms=START + 100 * STEP))

        await service.download_range("GAP/USDT", "1h", START, START + 199 * STEP, db=db)

        assert service.gateway.calls[0] == START


class _SessionGapGateway:
    """A market that closes: pages come back short but the data continues."""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.pages = 0

    async def fetch_ohlcv(self, symbol, timeframe, since_ms=None, limit=500):
        self.calls.append(since_ms or 0)
        self.pages += 1
        if self.pages > 3:
            return []
        start = since_ms or START
        # Far fewer rows than requested, as a weekend produces.
        return [[float(start + index * STEP), 1.0, 1.1, 0.9, 1.05, 0.0] for index in range(120)]


@pytest.mark.asyncio
class TestSessionGapPaging:
    async def test_forex_keeps_paging_after_a_short_page(self, db) -> None:
        """The "short page means end of data" rule is right for 24/7 crypto and
        wrong for FX, where it truncates the history to the first page."""
        gateway = _SessionGapGateway()
        service = MarketDataService.__new__(MarketDataService)
        service.gateway = gateway  # type: ignore[attr-defined]
        # EUR/USD routes to the external provider, so that is what the fake
        # stands in for here; the paging rule under test is the same either way.
        service._external_history = gateway  # type: ignore[attr-defined]

        await service.download_range("EUR/USD", "1h", START, START + 5000 * STEP, db=db)

        assert gateway.pages > 1, "a short page must not end the download on FX"

    async def test_crypto_still_stops_on_a_short_page(self, db) -> None:
        gateway = _SessionGapGateway()
        service = MarketDataService.__new__(MarketDataService)
        service.gateway = gateway  # type: ignore[attr-defined]

        await service.download_range("BTC/USDT", "1h", START, START + 5000 * STEP, db=db)

        assert gateway.pages == 1
