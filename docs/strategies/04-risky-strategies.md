# Risky strategies

> None of these is guaranteed to be profitable. They are grouped as **risky**
> because they trade against the trend, trade very often, or enter before the
> direction is confirmed. Expect more losing trades and larger cost drag.

Risk level is shown next to every strategy in the dashboard. A risky strategy
is not "better" or "worse" than a safe one; it fails differently.

---

## Volatility Breakout

**Key:** `volatility_breakout` — **File:** `backend/app/strategies/volatility_breakout.py`

### How it works

1. Measure the average candle range over the last `range_period` closed bars.
2. Project a fraction of it from the current candle open:
   `upper = open + breakout_factor x range`, `lower = open - breakout_factor x range`.
3. Enter when the close breaks that level, optionally requiring a volume
   surge and trend agreement.
4. Stop is a tight `atr_stop_multiplier x ATR`; the position is closed again
   when price falls back through the opposite trigger.

The range uses **closed** bars only (shifted by one), so the trigger for a
candle never contains that candle.

### Assumptions

* A move that exceeds a fraction of the recent range tends to continue for at
  least a short distance.
* Intraday volatility is persistent enough that today's range predicts today's
  move size.

### When it fails

* Quiet, rangebound sessions: price crosses the trigger repeatedly with no
  follow-through.
* Wide spreads: the entry is a taker order exactly when liquidity is worst.
* News spikes that reverse within one candle.

### Transaction cost sensitivity

**Very high.** This is the highest-frequency strategy in the platform and the
tight stop means the average winner is small. At 0.04 percent taker fee plus
0.02 percent slippage a round trip costs about 0.12 percent, which can be a
large share of the target. Raise `breakout_factor` and `min_volume_ratio` to
trade less.

### Overfitting risk

High. `breakout_factor` and `range_period` are easy to curve-fit. Use
walk-forward analysis and prefer values that work across several markets.

### Public references

* Williams, L. — *Long-Term Secrets to Short-Term Trading* (the volatility
  breakout / range projection idea is described publicly there).
* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* — ATR.

---

## RSI Divergence Reversal

**Key:** `rsi_divergence` — **File:** `backend/app/strategies/rsi_divergence.py`

### How it works

1. Compare price and RSI over a `lookback` window.
2. A bullish setup needs price **lower** than `lookback` bars ago, RSI
   **higher**, and RSI below `oversold`.
3. Bearish is the mirror image.
4. The position is closed as soon as RSI returns to neutral.

This is a deliberately simple, causal divergence measure (a comparison over a
fixed window) rather than a pivot-detection algorithm. It is easier to test and
cannot accidentally look into the future.

### Assumptions

* Momentum weakens before price turns.
* The market is not in a strong trend — enforced by the regime filter, which
  disables the strategy entirely in a trending regime by default.

### When it fails

* **Strong trends.** Divergences appear and persist for a long time while price
  keeps going. This is the classic way to lose an account, which is why
  `disable_in_trending_regime` defaults to true.
* Volatility expansions, where the stop is hit before the reversal happens.

### Transaction cost sensitivity

Medium. Trade frequency is moderate, but the targets are small because it aims
for a bounce rather than a trend.

### Overfitting risk

High. The `lookback`, RSI thresholds and the minimum gaps interact strongly.

### Public references

* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* — RSI.
* Lo, A., MacKinlay, A. C. (1988). *Stock Market Prices Do Not Follow Random
  Walks*. Review of Financial Studies.

---

## Squeeze Momentum

**Key:** `squeeze_momentum` — **File:** `backend/app/strategies/squeeze_momentum.py`

### How it works

1. A "squeeze" is on while the Bollinger bands sit **inside** the Keltner
   channel, i.e. volatility has compressed.
2. Wait for the squeeze to last at least `min_squeeze_bars`.
3. When it releases, take the direction of the momentum reading, optionally
   filtered by a trend EMA.
4. Exit when momentum flips sign, or on the stop, target or trailing stop.

### Assumptions

* Volatility is mean reverting: compression is followed by expansion.
* Momentum at the moment of release indicates the direction of the expansion.

The second assumption is the weak one, and it is why this strategy is
classified as risky: **a squeeze predicts movement, not direction.**

### When it fails

* False releases that immediately snap back.
* Long squeezes that leak out slowly instead of expanding.
* Choosing the wrong side of a genuine expansion, which happens often enough to
  matter.

### Transaction cost sensitivity

Medium to high. Entries cluster at the start of fast moves, where slippage is
worst.

### Overfitting risk

High: band period, channel multiplier, squeeze length and momentum threshold
are four interacting knobs.

### Public references

* Bollinger, J. (2001). *Bollinger on Bollinger Bands* — the squeeze concept.
* Keltner, C. (1960). *How to Make Money in Commodities* — the channel.
