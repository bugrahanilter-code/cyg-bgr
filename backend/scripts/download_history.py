"""Download historical candles for a research study.

Run from the backend directory:

    .venv/Scripts/python.exe scripts/download_history.py --months 24 --timeframe 15m
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow "python scripts/download_history.py" as well as "python -m scripts...".
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import asyncio
import time

from app.core.config import get_settings
from app.core.constants import timeframe_to_ms
from app.core.time_utils import to_ms, utcnow
from app.database.init_db import init_database
from app.database.session import SessionLocal
from app.exchange.binance import BinanceGateway
from app.market_data import store
from app.market_data.service import MarketDataService

DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Download candles for research")
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    args = parser.parse_args()

    init_database()
    settings = get_settings()
    gateway = BinanceGateway(market_type=settings.binance_market_type)
    service = MarketDataService(
        gateway,
        symbols=args.symbols,
        timeframe=args.timeframe,
        enable_websocket=False,
    )

    end_ms = to_ms(utcnow())
    start_ms = end_ms - args.months * 30 * 24 * 60 * 60 * 1000
    step = timeframe_to_ms(args.timeframe)
    expected = (end_ms - start_ms) // step

    print(f"Downloading {args.months} months of {args.timeframe} candles")
    print(f"Roughly {expected:,} candles per market, {len(args.symbols)} markets\n")

    for symbol in args.symbols:
        started = time.perf_counter()
        with SessionLocal() as db:
            try:
                stored = await service.download_range(
                    symbol, args.timeframe, start_ms, end_ms, db=db, max_requests=400
                )
                total = store.count_candles(db, symbol, args.timeframe)
                oldest = store.earliest_open_time(db, symbol, args.timeframe)
            except Exception as exc:
                print(f"  {symbol:12s} FAILED: {exc}")
                continue
        elapsed = time.perf_counter() - started
        coverage = (end_ms - (oldest or end_ms)) / (30 * 24 * 60 * 60 * 1000)
        print(
            f"  {symbol:12s} +{stored:6,} new, {total:7,} cached, "
            f"{coverage:5.1f} months of history, {elapsed:5.1f}s"
        )

    await gateway.close()
    print("\nDownload finished.")


if __name__ == "__main__":
    asyncio.run(main())
