# Medium risk strategies

> None of these is guaranteed to be profitable. They are the standard
> systematic families: they trade **with** the trend and use filters to avoid
> the worst conditions, but they still lose money in sideways markets.

---

## MACD Momentum

**Key:** `macd_momentum` — **File:** `backend/app/strategies/macd_momentum.py`

### How it works

1. Compute MACD (`fast_period`, `slow_period`) and its signal line.
2. Enter long when MACD crosses **above** its signal line, provided:
   * price is above the long-term `trend_ema` (if the trend filter is on),
   * MACD is above zero (if `require_zero_line` is on),
   * ADX is above `min_adx`, so the market is actually moving.
3. Exit on the opposite crossover, the ATR stop, the target or the trailing stop.

### Assumptions

* Momentum changes persist long enough to be traded after confirmation.
* A long-term average is a usable definition of "the trend".

### When it fails

* Sideways markets: MACD crosses back and forth and every crossing pays costs.
* Sharp reversals: the crossover confirms after a large part of the move.

### Transaction cost sensitivity

Medium. Trade frequency depends heavily on the timeframe; on 5m candles the
costs will dominate, on 4h they are minor.

### Overfitting risk

Medium. The 12/26/9 defaults are the widely published ones; changing them per
market is where overfitting starts.

### Public references

* Appel, G. — the original public description of MACD.
* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* — ADX, ATR.

---

## Ichimoku Cloud Trend

**Key:** `ichimoku_trend` — **File:** `backend/app/strategies/ichimoku_trend.py`

### How it works

1. Build the Ichimoku lines: conversion (tenkan), base (kijun) and the two
   cloud spans.
2. Enter long when the conversion line crosses above the base line **and**
   price is above the cloud **and** the cloud itself is bullish.
3. Exit when price closes back through the base line.

**Look-ahead note:** the cloud spans are shifted *forward* by `kijun_period`,
which is what the original system does. The cloud visible at bar *t* was
computed from data at bar *t − kijun_period*, so shifting forward never leaks
future information.

### Assumptions

* Multiple confirmations reduce false signals more than they cost in lateness.
* The cloud is a meaningful support/resistance zone.

### When it fails

* It is **slow**. By the time price is above the cloud and the lines have
  crossed, a large part of the move is gone.
* Flat markets where price oscillates through a thin cloud.

### Transaction cost sensitivity

Low to medium: it trades rarely because of the triple confirmation.

### Overfitting risk

Low to medium. The classic 9/26/52 settings are public and widely used; leaving
them alone is the honest default.

### Public references

* Hosoda, G. (Ichimoku Sanjin) — the original published system.
* Elliott, N. (2007). *Ichimoku Charts: An Introduction to Ichimoku Kinko Hyo*.

---

## SuperTrend Follower

**Key:** `supertrend_follow` — **File:** `backend/app/strategies/supertrend_follow.py`

### How it works

1. SuperTrend is an ATR band that trails price and flips between a bullish and
   a bearish state.
2. Enter when the state flips, provided the long-term trend filter and ADX
   agree.
3. The SuperTrend line itself is used as the protective stop when
   `use_supertrend_as_stop` is on, which is the natural stop for this system.
4. Exit when the state flips back.

The indicator is stateful (each bar depends on the previous one) and is
computed with an explicit loop that only ever reads bars up to the current one.

### Assumptions

* A volatility-scaled trailing stop is a reasonable definition of trend state.
* Trends persist longer than the band width.

### When it fails

* Choppy markets: the state flips repeatedly, producing a run of small losses.
* Gaps that jump straight through the band.

### Transaction cost sensitivity

Medium. Every flip is a round trip, so the multiplier directly controls the
cost: a smaller `multiplier` means more flips and more fees.

### Overfitting risk

Medium. `period` and `multiplier` are exactly the two parameters people tune
until the equity curve looks good. Use walk-forward analysis.

### Public references

* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* — ATR, the
  basis of the SuperTrend band.
* Olson, D. (2004). *Have trading rule profits in the currency markets
  declined over time?* Journal of Banking and Finance — on the decay of simple
  trend rules over time.
