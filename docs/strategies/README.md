# Strategies

Fourteen independent, publicly documented systematic families ship with the
platform, grouped by how aggressive they are. The dashboard shows the risk
level next to every strategy.

## Safe (4)

Few trades, wide stops, trend aligned, long-only by default.
Details: [06-safe-strategies.md](06-safe-strategies.md)

| Key | Idea | Main weakness |
| --- | --- | --- |
| `golden_cross` | 50/200 moving average cross | Gives back a lot at the exit |
| `dual_momentum` | Absolute momentum + trend alignment | Whipsawed by V-shaped reversals |
| `vwap_pullback` | Buy dips to VWAP inside a trend | Pullback becomes a reversal |
| `keltner_trend` | Channel break with four confirmations | Trades very rarely |

## Medium (6)

Standard systematic families with trend and strength filters.
Details: [05-medium-risk-strategies.md](05-medium-risk-strategies.md),
[07-adaptive-momentum.md](07-adaptive-momentum.md) and
[01-trend-following.md](01-trend-following.md),
[02-breakout-donchian.md](02-breakout-donchian.md)

| Key | Idea | Main weakness |
| --- | --- | --- |
| `trend_following` | Time series momentum, higher timeframe confirmed | Choppy ranges |
| `breakout_donchian` | N-bar channel breakout | False breakouts |
| `macd_momentum` | MACD crossover with trend filter | Sideways whipsaws |
| `ichimoku_trend` | Cloud + conversion/base cross | Slow to react |
| `supertrend_follow` | ATR trailing-stop state flips | Flip-flops in chop |
| `adaptive_momentum` | Scored 15m day trading, 1h trend gate | Chop, and cost drag if the score threshold is low |

## Risky (4)

Counter-trend, high frequency or direction-agnostic entries.
Details: [04-risky-strategies.md](04-risky-strategies.md) and
[03-mean-reversion.md](03-mean-reversion.md)

| Key | Idea | Main weakness |
| --- | --- | --- |
| `mean_reversion` | Bollinger/z-score reversion | Strong trends |
| `rsi_divergence` | Price/RSI disagreement reversal | Divergences persist in trends |
| `volatility_breakout` | Range projection from the open | Cost drag, false breaks |
| `squeeze_momentum` | Volatility compression release | A squeeze predicts movement, not direction |

## Why these families

They are **complementary** (what hurts one tends to help another),
**publicly documented** (no secret methods, no claim of privileged access) and
**simple enough to test honestly**.

## Shared warning

None of these strategies is guaranteed to be profitable. Every one of them has
documented market conditions in which it loses money, listed on its own page.
Backtest results describe the past only. "Safe" describes the structure of the
strategy, not the outcome.

## Adding a fourteenth strategy

1. Create `backend/app/strategies/my_strategy.py`
2. Subclass `BaseStrategy`, set `key`, `name`, `family`, `risk_level` and a
   Pydantic `params_model`, then implement `warmup_bars`, `prepare()` and
   `evaluate()`
3. Add it to `BUILTIN_STRATEGIES` in `backend/app/strategies/registry.py`
4. Add tests. The suite automatically checks every registered strategy for
   stop/target consistency and that it can actually produce an entry.
5. Write a documentation page including the conditions in which it loses money.

The dashboard picks the new strategy up automatically, including a settings
form generated from the parameter schema.
