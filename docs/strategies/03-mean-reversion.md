# Strategy 3 - Statistical Mean Reversion

**Key:** `mean_reversion` - **Family:** mean reversion - **File:**
`backend/app/strategies/mean_reversion.py`

> This strategy is NOT guaranteed to be profitable. Fading a strong trend is
> the single fastest way to lose an account, which is why this implementation
> is regime aware and refuses to trade in a trending market.

## How it works

1. **Regime gate (the most important rule).** If the Market Regime Engine
   reports a trending market, or if ADX is above `max_adx`, the strategy
   returns HOLD. It only looks for setups in ranging conditions. This behaviour
   is controlled by `disable_in_trending_regime` and it is on by default.
2. **Deviation measurement.** A rolling z-score of price over
   `zscore_period` bars, plus Bollinger bands over `bb_period`.
3. **Exhaustion confirmation.** RSI must be at or below `rsi_oversold` for a
   long, at or above `rsi_overbought` for a short.
4. **Location filter.** Optional VWAP filter: only buy below the rolling VWAP,
   only sell above it.
5. **Volatility ceiling.** Setups are skipped when ATR as a percentage of price
   exceeds `max_atr_pct`, and always when the regime is EXTREME_VOLATILITY.
6. **Risk.** Stop = `atr_stop_multiplier` x ATR (tighter than the trend
   strategies by default). The target is the Bollinger middle band, i.e. the
   mean itself; if that is already behind price, a fallback R multiple is used.
7. **Exit.** As soon as the z-score returns inside `zscore_exit`, the position
   is closed - the trade thesis is over once price is back at the mean.

## Assumptions

* In the absence of a trend, price oscillates around a slowly moving mean.
* Extreme short-term deviations are partly caused by temporary order-flow
  imbalance and are corrected.
* The distribution of returns is stable enough for a z-score to be meaningful
  over the chosen window.

## Where it can work

Ranging, low-to-normal volatility markets on short timeframes (5m to 1h),
typically during consolidation phases between trends.

## When it fails

* **Strong trends.** A z-score of -2 in a bear market is followed by -3, then
  -4. The regime filter exists for this, but no filter is perfect.
* **Regime transitions.** The moment a range breaks into a trend is the worst
  possible moment for this strategy.
* **Volatility expansion.** The mean itself moves faster than the reversion.
* **Fat tails.** Crypto has more extreme moves than a normal distribution
  implies, so a "2 sigma" event is much more common than the maths suggests.

## Transaction cost sensitivity

**Very high.** Mean reversion targets small moves back to the mean, so costs
consume a large share of the edge. With 0.04 percent taker fees and 0.02
percent slippage, a round trip costs about 0.12 percent; if the average target
is 0.5 percent, roughly a quarter of the gross profit is gone before funding.
Widen `zscore_entry` and the target if your fees are higher.

## Overfitting risk

**Highest of the three.** There are many knobs (z-score period and threshold,
RSI levels, band width, ADX ceiling) and each one can be tuned to make a
historical curve look good. Treat any impressive backtest here with suspicion,
always run walk-forward analysis, and remember that mean reversion strategies
tend to show a high win rate with rare, very large losses - a pattern that is
easy to mistake for a good system.

## Known risks

High win rate, low average win, occasional catastrophic loss. Position sizing
and the hard stop are what keep that tail survivable. Never remove the stop
loss to "let it come back".

## Public references

Pointers to publicly available literature; verify each source yourself.

* Poterba, J., Summers, L. (1988). *Mean Reversion in Stock Prices: Evidence
  and Implications*. Journal of Financial Economics.
* Lo, A., MacKinlay, A. C. (1988). *Stock Market Prices Do Not Follow Random
  Walks: Evidence from a Simple Specification Test*. Review of Financial
  Studies.
* Avellaneda, M., Lee, J. H. (2010). *Statistical Arbitrage in the U.S.
  Equities Market*. Quantitative Finance.
* Bollinger, J. (2001). *Bollinger on Bollinger Bands*.
* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* - RSI.
* Harvey, C., Liu, Y., Zhu, H. (2016). *... and the Cross-Section of Expected
  Returns*. Review of Financial Studies - on multiple testing and why most
  discovered "edges" do not survive.
