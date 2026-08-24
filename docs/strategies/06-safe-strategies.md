# Safe strategies

> "Safe" here means **structurally more conservative**, not profitable and
> certainly not risk free. These strategies take few trades, use wide stops,
> trade only with the dominant trend and are long-only by default.
>
> A wide stop is not a small loss: it is a *less frequent* loss. You can still
> lose money on every one of these.

---

## Golden Cross Trend

**Key:** `golden_cross` — **File:** `backend/app/strategies/golden_cross.py`

### How it works

1. Two moving averages, fast (default 50) and slow (default 200).
2. Enter long when the **gap between them first becomes meaningful** in the
   bullish direction (at least `min_separation_pct`).
3. Exit on the opposite cross, the wide ATR stop, the target or the trailing
   stop.

**Why the gap and not the raw crossover:** on the exact crossover bar the two
averages sit on top of each other, so the gap is close to zero by definition.
Requiring a minimum separation on that bar rejects essentially every signal —
this was a real bug found by running the strategy, and the confirmed-gap
trigger is the fix.

### Assumptions

* A small number of large trends per year carries most of the return.
* Being late is acceptable if it removes most false signals.

### When it fails

* It gives back a large part of every trend at the exit, by construction.
* Repeated crosses during a long consolidation.
* Very few trades means very high sample-size uncertainty.

### Transaction cost sensitivity

Very low: a handful of trades per year at most on higher timeframes.

### Overfitting risk

Low. The 50/200 pair is the most widely published setting in existence, which
also means any edge is well known and probably arbitraged.

### Public references

* Brock, W., Lakonishok, J., LeBaron, B. (1992). *Simple Technical Trading
  Rules and the Stochastic Properties of Stock Returns*. Journal of Finance.
* Faber, M. (2007). *A Quantitative Approach to Tactical Asset Allocation*.
  Journal of Wealth Management.

---

## Dual Momentum

**Key:** `dual_momentum` — **File:** `backend/app/strategies/dual_momentum.py`

### How it works

1. Measure **absolute momentum**: the percentage change over
   `momentum_period` bars.
2. Enter long only when that momentum exceeds `min_momentum_pct` **and** price
   is above both the medium and the long-term EMA.
3. Close as soon as momentum falls back below `exit_momentum_pct`.

This is the single-asset half of Gary Antonacci's publicly documented dual
momentum idea (absolute momentum as a market-participation filter). The
relative-momentum half, which ranks several assets against each other, is a
natural next step and is listed in the roadmap.

### Assumptions

* Assets that have gone up over a long window continue more often than not.
* Staying out during negative momentum avoids the worst drawdowns.

### When it fails

* Sharp V-shaped reversals: it exits at the bottom and re-enters near the top.
* Long sideways periods just above the momentum threshold.

### Transaction cost sensitivity

Very low. It holds for long stretches and trades rarely.

### Overfitting risk

Low to medium. The main knob is `momentum_period`; results should be stable
across a range of values, not sharp at one.

### Public references

* Antonacci, G. (2014). *Dual Momentum Investing*.
* Moskowitz, T., Ooi, Y. H., Pedersen, L. H. (2012). *Time Series Momentum*.
  Journal of Financial Economics.

---

## VWAP Trend Pullback

**Key:** `vwap_pullback` — **File:** `backend/app/strategies/vwap_pullback.py`

### How it works

1. Confirm an uptrend: price above the long-term EMA.
2. Wait for price to **pull back** to within `max_distance_atr` of the rolling
   VWAP, from above.
3. Require RSI to stay above `rsi_floor`, so a pullback that has become a
   breakdown is rejected.
4. Exit when price loses the long-term trend line, or on the stop/target.

Buying a dip inside a trend rather than chasing a breakout means the stop is
naturally closer to the entry, which is why the position size for the same risk
is larger — the Risk Engine handles that automatically.

### Assumptions

* Trends progress in waves, and VWAP acts as a reference price institutions
  trade around.
* A pullback with intact momentum is a discount, not a warning.

### When it fails

* When the pullback is the start of a reversal. The RSI floor helps but does
  not eliminate this.
* Trends that never pull back: the strategy simply misses them.

### Transaction cost sensitivity

Medium. It trades more than the other safe strategies because pullbacks are
more frequent than crossovers.

### Overfitting risk

Medium. `max_distance_atr` and `rsi_floor` interact; tune them together and
validate out of sample.

### Public references

* Berkowitz, S., Logue, D., Noser, E. (1988). *The Total Cost of Transactions
  on the NYSE*. Journal of Finance — the origin of VWAP as a benchmark.
* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* — RSI, ATR.

---

## Keltner Channel Trend

**Key:** `keltner_trend` — **File:** `backend/app/strategies/keltner_trend.py`

### How it works

1. Build a Keltner channel: an EMA with an ATR band around it.
2. Enter only when price **closes outside** the band and, at the same time:
   * price is above the long-term EMA,
   * the higher timeframe agrees,
   * ADX confirms a real trend,
   * volume confirms the move.
3. Hold until price closes back through the middle line.

Four simultaneous confirmations make this the most selective strategy in the
platform. That is deliberate: it should stand aside most of the time.

### Assumptions

* A close outside a volatility band in an established trend indicates
  continuation, not exhaustion.
* Multiple independent filters remove more noise than signal.

### When it fails

* Exhaustion moves: the final push of a trend also closes outside the band.
* Very few trades, so the results are statistically fragile.
* Stacking filters can remove so many signals that whole years pass with
  nothing to trade.

### Transaction cost sensitivity

Low. It trades rarely and holds for the length of a trend leg.

### Overfitting risk

Medium. Every added filter is another parameter, and four filters can be tuned
until the past looks perfect. Prefer the defaults, and validate with
walk-forward analysis.

### Public references

* Keltner, C. (1960). *How to Make Money in Commodities* — the original channel.
* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* — ATR, ADX.
* Hurst, B., Ooi, Y. H., Pedersen, L. H. (2017). *A Century of Evidence on
  Trend-Following Investing*. Journal of Portfolio Management.
