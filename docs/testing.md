# Testing

```bash
cd backend
pip install -r requirements-dev.txt
pytest                    # the whole suite
pytest -k risk            # one area
pytest --cov=app          # with coverage
```

Tests run against an **in-memory SQLite database** and a **mock exchange**, so
they never touch the network and never need Binance credentials.

## What is covered

| File | Focus |
| --- | --- |
| `test_indicators.py` | Indicator maths and an explicit look-ahead check |
| `test_strategies.py` | All three strategies, stop/target consistency, regime gating |
| `test_risk_engine.py` | Every rejection rule of the Risk Engine |
| `test_position_sizing.py` | Sizing, caps, exchange filters, liquidation estimate |
| `test_pnl.py` | Gross/net PnL, fees, funding direction |
| `test_execution.py` | Order validation, idempotency, duplicate suppression, live guard |
| `test_backtest.py` | Metrics, costs, daily limits, truncated-history look-ahead test |
| `test_reconciliation.py` | Local vs exchange mismatches |
| `test_paper_trading.py` | End-to-end paper round trip, persistent kill switch |
| `test_api.py` | API contract and the live-trading safety defaults |

## The look-ahead test

`test_no_lookahead_truncated_history_matches` runs the same backtest twice: once
on the full candle history and once on a truncated copy. Any trade that closed
well before the truncation point must be identical in both runs. If a strategy
ever peeks at future data, the two lists diverge and the test fails.

## Frontend

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```
