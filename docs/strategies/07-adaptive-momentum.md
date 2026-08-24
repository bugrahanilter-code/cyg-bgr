# Adaptive EMA + RSI + ATR Momentum Day Trader

**Key:** `adaptive_momentum` — **Risk level:** medium —
**File:** `backend/app/strategies/adaptive_momentum.py`

> This strategy is NOT guaranteed to be profitable. It was built to a
> specification and then tested honestly; the research verdict lives in
> [docs/research/adaptive-momentum-study.md](../research/adaptive-momentum-study.md).

## How it works

An intraday momentum system on **15 minute** candles, gated by a **1 hour**
trend filter. Seven components each contribute to a 0-100 signal score:

| Component | Points | Long condition |
| --- | --- | --- |
| 1h trend | 20 | EMA50 > EMA200 **and** 1h close > EMA200 |
| EMA structure | 15 | EMA20 > EMA50 **and** close > EMA20 |
| RSI momentum | 10 | 52 < RSI(14) < 72 |
| Volume | 15 | volume > SMA(20) x 1.20 |
| Trend strength | 10 | ADX(14) > 20 |
| Location | 10 | close > VWAP |
| Breakout | 20 | high breaks the highest high of the previous 5 candles |

Short is the exact mirror (RSI band 28-48, everything else inverted).

Only scores at or above `min_signal_score` (default 70) are traded. The score
is stored on every signal together with the per-component breakdown, so a
rejected setup can always be explained: *"score 55/100, missing volume,
breakout"*.

Setting `require_all_hard_rules` to true turns the score back into a strict
AND of all seven conditions.

## Risk and exits

* **Stop:** `atr_stop_multiplier` x ATR(14), default 1.5
* **Target:** `take_profit_r` x the stop distance, default 2.0R
* **Exit models**, selectable with `exit_model`:
  * `atr` — ATR trailing stop at `trailing_atr_multiplier` x ATR
  * `ema` — close through the fast EMA closes the position
  * `hybrid` — both, whichever triggers first
* **Volatility band:** no trade when ATR/price is below `min_atr_pct` (too
  quiet to cover costs) or above `max_atr_pct`
* **Regime:** stands aside in an EXTREME_VOLATILITY regime; optionally
  restricted to trending regimes only

Position size comes from the Risk Engine: equity x risk-per-trade divided by
the stop distance, then capped by exposure, margin and exchange rules. Leverage
changes the margin required, never the risk taken.

## Look-ahead safety

Three places could leak the future, and all three are closed:

1. **The 1h trend** is computed from completed 1h candles and shifted one
   bucket before being mapped back onto the 15m bars, so a 15m bar never sees
   the hourly candle it is currently inside.
2. **The breakout level** uses `highest(high, N).shift(1)`, so the candle being
   tested is never part of the level it must break.
3. **`evaluate()` reads one row.** It cannot look forward even by accident.

The test suite asserts property 1 directly by truncating the series and
checking that no past value changed.

## Assumptions

* Intraday momentum persists for long enough to pay for the round trip.
* Agreement between independent signals (trend, volume, location, strength)
  is more informative than any one of them alone.
* Volatility, measured by ATR, is a usable proxy for the risk of a position.

## When it fails

* **Range-bound markets.** The breakout component fires on noise and the
  position is stopped out shortly after entry.
* **Regime transitions.** The 1h filter is by construction late, so the first
  hours of a reversal are traded in the wrong direction.
* **Low volatility.** The ATR floor exists for this, but a market that is
  quiet *and* trending will still produce small winners that costs eat.
* **A score threshold set too low.** Dropping to 60 roughly doubles the trade
  count, and the extra trades are the low-conviction ones.

## Transaction cost sensitivity

**High.** This is a day-trading system: with 0.05 percent taker fee and 0.05
percent slippage, a round trip costs roughly **0.20 percent** of notional
before funding. At 2R targets on a 1.5 ATR stop, that is a meaningful fraction
of the average winner. The research report includes a slippage sweep
(0.02 / 0.05 / 0.10 / 0.15 percent); a configuration that only works at the
lowest assumption is reported as fragile, not as a strategy.

## Overfitting risk

**High**, and deliberately measured rather than assumed away:

* eleven tunable parameters is a lot of freedom
* the study uses a chronological 60/20/20 split and optimises on the
  in-sample block only
* the search is a coordinate sweep, not a brute-force grid, which produces the
  parameter stability data as a by-product
* each swept parameter is reported as a plateau or a spike; a spike is flagged
  as an overfitting risk

## Parameters

Every value in the table above is a parameter, plus the exit model, the
volatility band, the higher timeframe and its two EMA lengths. Full list and
ranges: `AdaptiveMomentumParams` in the strategy file, or the settings form the
dashboard generates from it.

## Public references

* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* — RSI, ATR
  and ADX, three of the seven components.
* Moskowitz, T., Ooi, Y. H., Pedersen, L. H. (2012). *Time Series Momentum*.
  Journal of Financial Economics.
* Berkowitz, S., Logue, D., Noser, E. (1988). *The Total Cost of Transactions
  on the NYSE*. Journal of Finance — VWAP as a benchmark price.
* Bailey, D., Borwein, J., Lopez de Prado, M., Zhu, Q. (2014).
  *Pseudo-Mathematics and Financial Charlatanism*. Notices of the AMS — why
  a multi-parameter intraday system needs out-of-sample validation before it
  means anything.
