# Architecture

## Layer diagram

```
Market Data  (Binance REST + WebSocket, local candle cache)
      |
Market Regime Engine        (TRENDING / RANGING / volatility buckets)
      |
Strategy Engine             (3 independent, configurable strategies)
      |
Signal Engine               (validation, deduplication, persistence)
      |
Risk Engine                 (VETO POWER - can reject any signal)
      |
Portfolio Engine            (position sizing result, balances, daily stats)
      |
Execution Engine            (the ONLY module that can send a real order)
      |
Exchange Gateway            (Binance / Simulated)
      |
Trade Journal  ->  Dashboard (read-only client)
```

Supporting modules that run beside the main pipeline:

| Module | Responsibility |
| --- | --- |
| `backtesting/` | Bar-by-bar simulator, cost model, metrics, walk-forward |
| `paper_trading` (via `SimulatedGateway`) | Real prices, simulated fills |
| `reconciliation/` | Compares the local database with the exchange |
| `monitoring/` | Health of every component, heartbeat, event log |

## Hard rules encoded in the code

1. **A strategy cannot place an order.** It returns a `StrategySignal` object.
   Only `ExecutionEngine` calls `gateway.create_order`.
2. **The Risk Engine has the last word.** `RiskEngine.evaluate()` returns a
   `RiskDecision`; if `approved` is false, nothing happens.
3. **Live trading is off by default.** Three independent switches must all be
   true: `LIVE_TRADING_ENABLED` in the environment, the dashboard confirmation
   stored in `bot_state`, and `allow_real_orders` on the execution engine.
4. **No look-ahead bias.** Indicators are causal, the Donchian channel is
   shifted by one bar, strategies only ever read row `i` of a prepared frame,
   and the backtester fills at the open of bar `i+1`.
5. **Secrets never leave the backend.** They are encrypted at rest with Fernet
   and scrubbed from every log record.
6. **State mismatch stops trading.** If the local database and Binance disagree
   about positions or balance, `ReconciliationEngine` flags a mismatch and the
   Risk Engine refuses every new entry.

## Why the frontend is dumb on purpose

The dashboard only calls the REST API. It holds no trading logic, no strategy
parameters and no risk rules. You can delete the whole `frontend/` folder and
the trading engine keeps running; you can also replace it with a completely
different UI without touching the backend.

## Restart recovery sequence

`TradingEngine.recover_state()` runs before the loop starts:

1. connect to the exchange
2. read balance, open positions and open orders
3. compare them with the local database (reconciliation)
4. restore the last processed candle per strategy so a restart cannot replay
   old signals
5. keep an armed emergency stop armed

Only after this does the engine begin evaluating strategies again.

## Extension points

* **New strategy** - subclass `BaseStrategy`, call `register_strategy()`.
* **New coin** - insert a row in the `symbols` table and enable it in the
  dashboard. No symbol is hard-coded anywhere in the pipeline.
* **New exchange** - implement `ExchangeGateway`.
* **Machine learning** - a model can be added as an extra strategy, or as a
  confidence filter in the Signal Engine. The deterministic strategy and risk
  layers stay in charge of the actual order decision.
