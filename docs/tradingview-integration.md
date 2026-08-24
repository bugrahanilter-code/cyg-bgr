# TradingView integration

## Summary

TradingView is used for **charts** and **screener context**. It is deliberately
**not** used as the source of the candles that strategies and backtests run on.
Those come from Binance.

This document explains why, because "get the data from TradingView" sounds like
a straightforward swap and is not.

## What TradingView actually offers

| Product | What it is | Free? | Gives us OHLCV? |
| --- | --- | --- | --- |
| Embedded widgets (Advanced Chart, ticker tape, screener) | An iframe rendering TradingView's own data | Yes | **No** — the data stays inside their frame |
| Lightweight Charts | A charting library. You supply the data | Yes (Apache 2.0) | No, it is a renderer |
| Advanced Charts / Trading Platform | A charting library that fetches data from *your* server over the UDF protocol | Yes, after requesting access | No, it consumes your data |
| Screener / scanner endpoint | The JSON endpoint behind their public crypto screener | Undocumented | Partially — last price, 24h OHLC, volume, indicators. Not history |
| A REST or WebSocket history API | — | — | **Does not exist publicly** |

There is no documented endpoint for candle history. Libraries that appear to
provide one work by reverse-engineering the private WebSocket their charts use.
That needs a TradingView account, breaks without notice when they change the
protocol, and is outside what their terms allow.

## Why it would not help even if it worked

TradingView does not produce crypto price data. `BINANCE:BTCUSDT.P` on
TradingView **is Binance's data**, relayed. Pulling it second-hand would mean:

* the same numbers, with extra latency and an extra point of failure
* a backtest running on a series that can silently drift from what the execution
  engine will actually trade against
* a dependency that breaks the moment an undocumented protocol changes

The candles a backtest uses must be the candles the exchange will fill against.
That argues for going to the exchange directly, and it is why
`app/exchange/binance.py` stays the only source of OHLCV.

## What is wired up

### 1. Screener context — `app/market_data/providers/tradingview.py`

Calls the public scanner endpoint and returns, per market: technical rating
(`Recommend.All` and its published wording), RSI, ATR, relative volume, daily
volatility. The Markets page shows these next to the Binance figures.

Three rules apply to this data:

* **It is never an input to a trading decision.** No strategy, risk check or
  order sizing reads a `tv_` field. It is there for a human choosing what to
  put on the watchlist.
* **Failure is not an error.** If the endpoint is unreachable the provider logs
  it, records `last_error`, and returns an empty mapping. The Markets page then
  shows Binance data with a banner explaining the empty columns.
* **It is cached** for five minutes. These are daily-horizon indicators; polling
  them every few seconds would be rude and pointless.

### 2. Charts — `frontend/src/components/TradingViewChart.tsx`

The free embedded Advanced Chart widget. It renders TradingView's own data in
their iframe. Nothing it displays is read back into the platform.

### 3. A UDF datafeed — `app/api/routes/udf.py`

`/api/udf/config`, `/search`, `/symbols`, `/history` and `/time` implement the
REST contract TradingView's *Advanced Charts* library speaks.

This serves **our** candles, from our own database, in their protocol. When the
library is dropped in (it is free but access has to be requested from
TradingView, so the file is not vendored here), the chart will show exactly the
candles the backtester used. A chart that quietly disagrees with the backtester
is worse than no chart at all, and this is the fix for that.

The datafeed is already usable today with any client that speaks UDF:

```bash
curl "http://localhost:8000/api/udf/history?symbol=BTCUSDT&resolution=60&from=1735689600&to=1738368000"
```

## Resolution mapping

| UDF resolution | Platform timeframe |
| --- | --- |
| `1`, `3`, `5`, `15`, `30` | `1m`, `3m`, `5m`, `15m`, `30m` |
| `60`, `120`, `240`, `360`, `480`, `720` | `1h`, `2h`, `4h`, `6h`, `8h`, `12h` |
| `1D` / `D`, `3D`, `1W` / `W` | `1d`, `3d`, `1w` |

## If you want to change the decision

The provider layer is pluggable on purpose. `MarketContextProvider` in
`app/market_data/providers/base.py` is the interface; adding a second context
source is a new file and one registration. Replacing the *candle* source is a
much larger decision and should be argued for on the grounds above, not on
convenience.
