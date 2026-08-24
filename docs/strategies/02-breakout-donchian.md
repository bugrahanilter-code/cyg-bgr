# Strategy 2 - Donchian Channel Breakout

**Key:** `breakout_donchian` - **Family:** breakout - **File:**
`backend/app/strategies/breakout_donchian.py`

> This strategy is NOT guaranteed to be profitable. False breakouts are its
> normal, expected behaviour.

## How it works

1. **Entry channel.** The highest high and lowest low of the previous
   `channel_period` candles, computed with a **one bar shift**. This shift is
   what removes look-ahead bias: the level tested by bar `t` is built from bars
   `t-period .. t-1` and never contains bar `t` itself.
2. **Breakout with a buffer.** A long requires
   `close > upper + breakout_buffer_atr x ATR`. The buffer filters marginal
   pokes through the level.
3. **Volume confirmation.** Optional: current volume divided by its rolling
   average must be at least `min_volume_ratio`.
4. **Trend filter.** Optional: longs only above the `trend_ema`, shorts only
   below it, so the strategy does not fade the dominant direction.
5. **Volatility band.** The breakout is skipped when ATR as a percentage of
   price is outside `[min_atr_pct, max_atr_pct]` - dead markets produce noise,
   extreme markets produce unmanageable risk.
6. **Risk.** Stop = `atr_stop_multiplier` x ATR, target = stop x
   `take_profit_r`, optional ATR trailing stop.
7. **Exit.** A shorter opposite channel (`exit_channel_period`) closes the
   position, plus the usual stop, target and Risk Engine exits.

## Assumptions

* A move beyond a recent extreme carries information: it is more likely to
  continue than to revert immediately.
* Volatility expansion follows volatility compression.
* Slippage on the breakout candle is tolerable given the ATR-scaled stop.

## Where it can work

Markets that alternate between quiet consolidation and sharp expansions - a
common description of BTC and ETH. Works best on 15m to 4h timeframes.

## When it fails

* **Range-bound markets.** Repeated false breakouts, the single most common
  failure mode of the family.
* **Thin liquidity.** The breakout candle is exactly when slippage is worst.
* **News spikes.** A wick through the channel followed by an immediate reversal
  triggers entry and stop in quick succession.
* **Crowded levels.** Obvious round numbers and highs attract stop hunting.

## Transaction cost sensitivity

**High.** Breakout entries are taker orders during fast moves, which is the
most expensive moment to trade. The strategy is only viable if the average
winner is several times the round-trip cost. Increasing `breakout_buffer_atr`
and `min_volume_ratio` reduces trade count and cost drag, at the price of later
entries.

## Overfitting risk

Medium to high. `channel_period` is the classic curve-fitted parameter. A
system that only works at exactly 20 bars and breaks at 18 or 22 is fitted to
noise. Use the walk-forward mode and prefer parameter *plateaus*, not peaks.

## Known risks

Breakout systems have long losing streaks between the few large winners. The
consecutive-loss limit and the cooldown in the Risk Engine exist precisely for
that pattern.

## Public references

Pointers to publicly available material; verify each source yourself.

* Donchian, R. - the Donchian channel is a long-standing public technical
  construct named after him.
* *The Original Turtle Trading Rules* - the Dennis/Eckhardt channel breakout
  system, published free of charge by former Turtles.
* Lukac, L., Brorsen, B. W., Irwin, S. (1988). *A test of futures market
  disequilibrium using twelve different technical trading systems*. Applied
  Economics - includes channel breakout systems.
* Faber, M. (2007). *A Quantitative Approach to Tactical Asset Allocation*.
  Journal of Wealth Management - simple public trend timing rules.
* Bailey, D., Borwein, J., Lopez de Prado, M., Zhu, Q. (2014).
  *Pseudo-Mathematics and Financial Charlatanism*. Notices of the AMS - why
  backtest overfitting matters for exactly this kind of parameter.
