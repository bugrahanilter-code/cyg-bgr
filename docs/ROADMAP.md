# Status and roadmap

This document is deliberately honest about what is implemented, what is
partially implemented, and what is not there yet.

## Verification status

Verified by actually running it on 2026-08-24 (Windows 11, Python 3.14,
Node 26):

* 105 backend tests pass, `ruff check` and `ruff format --check` are clean
* frontend type check, lint and production build are clean
* the backend boots, creates its schema, connects to the Binance public
  WebSocket and streams live BTC/USDT and ETH/USDT prices
* the trading engine runs in paper mode, reconciliation reports IN_SYNC and
  every health component reports OK
* a real 90-day backtest over 8,956 BTC/USDT 15m candles completes in about
  11 seconds and reports its costs (fees, funding, slippage) honestly
* the dashboard renders every page, including the charts

**Not verified:** the Docker Compose path (the test machine has CPU
virtualization disabled in its BIOS, so Docker Desktop cannot start) and live
trading against a real Binance account.

## Implemented in this MVP

| Area | Status |
| --- | --- |
| Project skeleton, Docker Compose, PostgreSQL, Alembic | Done |
| Binance market data (REST history + WebSocket stream + REST fallback) | Done |
| Local candle cache and staleness detection | Done |
| Market Regime Engine (trend + volatility classification) | Done |
| Three strategies with fully configurable parameters | Done |
| Signal Engine with per-candle deduplication | Done |
| Risk Engine with 20+ rejection rules | Done |
| Position sizing from stop distance, exchange filters, margin | Done |
| Portfolio, balances, daily statistics, trade journal | Done |
| Backtest engine with fees, slippage, funding, execution delay | Done |
| Backtest metrics, equity/drawdown/monthly/distribution | Done |
| Walk-forward analysis with in-sample / out-of-sample split | Done |
| Paper trading on live prices | Done |
| Execution Engine with idempotency and order verification | Done |
| Live trading path (futures market orders + exchange-side SL/TP) | Implemented, needs real-account validation |
| Reconciliation engine and restart recovery | Done |
| Emergency stop (3 levels, persisted) | Done |
| Monitoring, health, structured logging with secret redaction | Done |
| Dashboard (9 pages) | Done |
| Tests (indicators, strategies, risk, sizing, PnL, execution, backtest, reconciliation, API) | Done |
| GitHub Actions CI | Done |

## Partially implemented / needs real-world validation

* **Live trading has not been executed against a real Binance account** by the
  author of this codebase. Validate on the **testnet** first, with a tiny
  balance, and watch the first trades closely.
* **Spot live trading** places market and limit orders but manages stop loss
  and take profit locally (spot has no reduce-only flag and no native
  STOP_MARKET semantics identical to futures). Futures is the better tested
  path.
* **Liquidation price** is a simplified isolated-margin estimate. Binance uses
  a tiered maintenance margin table that is not replicated.
* **Funding** uses a fixed configurable rate rather than the historical funding
  series. Real funding varies over time.
* **Partial fills** are recorded but not split into multiple position entries.
* **Multi-position per symbol** is intentionally blocked by default
  (`one_position_per_symbol`).

## Not implemented yet (natural next steps)

1. **Historical funding rate download** for more accurate backtests.
2. **Order book / depth-based slippage model** instead of a flat percentage.
3. **Portfolio-level correlation limits** (e.g. do not go long BTC and ETH at
   full size simultaneously).
4. **Notifications** (Telegram, email). The preferences model exists; the
   senders do not.
5. **Multi-exchange support.** The `ExchangeGateway` interface is ready for it.
6. **Machine learning extension point.** The architecture leaves room for an ML
   model as an additional strategy or as a confidence filter, but no model
   ships with the platform on purpose: the first version is deterministic and
   testable.
7. **Authentication on the API** for non-localhost deployments.
8. **WebSocket push to the dashboard** (currently the UI polls, which is simple
   and reliable).
9. **Parameter optimisation UI** beyond walk-forward (with strong overfitting
   warnings).

## Known limitations to keep in mind

* Backtests use candle data, so intrabar sequencing is an assumption. The
  engine deliberately assumes the stop is hit before the target when both fall
  inside one candle.
* Fewer than ~30 trades in any result is statistical noise.
* The platform can only be as good as its risk settings. Raising risk does not
  raise expected profit.
