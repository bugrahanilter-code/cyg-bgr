# Strategies

Three independent, publicly documented systematic families ship with the
platform:

| Key | Family | Trades best in | Main weakness |
| --- | --- | --- | --- |
| [`trend_following`](01-trend-following.md) | Time series momentum | Persistent trends | Choppy ranges |
| [`breakout_donchian`](02-breakout-donchian.md) | Channel breakout | Volatility expansion | False breakouts |
| [`mean_reversion`](03-mean-reversion.md) | Statistical reversion | Quiet ranges | Strong trends |

They were chosen because they are **complementary** (what hurts one tends to
help another), **publicly documented** (no secret sauce, no claim of insider
methods) and **simple enough to test honestly**.

## Shared warning

None of these strategies is guaranteed to be profitable. Every one of them has
documented market conditions in which it loses money, listed in its own page.
Backtest results describe the past only.

## Adding a fourth strategy

1. Create `backend/app/strategies/my_strategy.py`
2. Subclass `BaseStrategy`, define a Pydantic `params_model`, implement
   `warmup_bars`, `prepare()` and `evaluate()`
3. Register it in `backend/app/strategies/registry.py`
4. Add unit tests in `backend/tests/test_strategies.py`
5. Write a documentation page like the three above, including the failure modes

The dashboard picks the new strategy up automatically, including a settings
form generated from the parameter schema.
