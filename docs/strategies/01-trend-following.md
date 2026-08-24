# Strategy 1 - Trend Following / Time Series Momentum

**Key:** `trend_following` - **Family:** trend - **File:**
`backend/app/strategies/trend_following.py`

> This strategy is NOT guaranteed to be profitable. It is a publicly documented
> systematic approach with well known weaknesses, listed below.

## How it works

1. **Higher timeframe filter.** An EMA of the higher timeframe (default 4h) is
   computed from *completed* higher-timeframe candles only and mapped back onto
   the trading timeframe. Longs require price above it, shorts below it.
2. **Trend structure.** On the trading timeframe the EMA stack must agree:
   `fast EMA > slow EMA` and `close > trend EMA` for a long (mirrored for a
   short).
3. **Trend strength.** ADX must be above `min_adx`, otherwise the market is
   treated as directionless and the signal is skipped.
4. **Momentum trigger.** The rate of change over `momentum_period` bars must
   exceed `momentum_threshold`.
5. **Do not chase.** The entry is rejected when price is further than
   `max_entry_distance_atr` ATR away from the fast EMA.
6. **Volatility-scaled risk.** Stop loss = `atr_stop_multiplier` x ATR.
   Take profit = stop distance x `take_profit_r`. An optional ATR trailing stop
   follows the best price reached.
7. **Exit.** The position is closed when the EMA stack flips, or by the stop,
   the target, or the Risk Engine.

## Assumptions

* Price series exhibit positive autocorrelation over the chosen horizon
  (trends persist longer than a random walk implies).
* Volatility is a usable proxy for risk, so ATR-based stops keep the risk per
  trade roughly constant across regimes.
* A small number of large winners pays for many small losers. The win rate is
  expected to be **below 50 percent**.

## Where it can work

Markets with persistent directional moves and enough liquidity: BTC/USDT and
ETH/USDT perpetuals on higher timeframes (15m and above) during expansion
phases.

## When it fails

* **Choppy, range-bound markets.** The classic failure mode: repeated
  whipsaws, each one paying the spread, the fee and the stop.
* **Sudden reversals.** Trend following is always late to a top or a bottom by
  construction.
* **Volatility spikes.** ATR widens, stops move further away, position size
  shrinks; a gap can still jump the stop.
* **Long flat periods.** Months without a trend produce a slow bleed of costs.

## Transaction cost sensitivity

Medium. Trade frequency is moderate, but every whipsaw pays the full round trip
(2 x taker fee + 2 x slippage + funding while the position is open). On a 15m
timeframe with 0.04 percent taker fees plus 0.02 percent slippage, roughly
0.12 percent per round trip is lost to costs. Raise `momentum_threshold` and
`min_adx` to trade less and pay less.

## Overfitting risk

High if the EMA lengths are tuned per market on the full history. Mitigations
built into this platform:

* every parameter is explicit and visible, not buried in the code
* the Backtest Lab supports walk-forward analysis with out-of-sample windows
* the backtest warns when fewer than 30 trades were generated

Change one parameter at a time and prefer values that work across BOTH markets
and across several folds rather than the single best number.

## Known risks

Leverage magnifies drawdowns; funding costs accumulate on long-held perpetual
positions; a trend can end the moment the entry fills.

## Public references

These are pointers to publicly available literature on this family of
techniques. Please verify each source yourself.

* Moskowitz, T., Ooi, Y. H., Pedersen, L. H. (2012). *Time Series Momentum*.
  Journal of Financial Economics.
* Jegadeesh, N., Titman, S. (1993). *Returns to Buying Winners and Selling
  Losers: Implications for Stock Market Efficiency*. Journal of Finance.
* Hurst, B., Ooi, Y. H., Pedersen, L. H. (2017). *A Century of Evidence on
  Trend-Following Investing*. Journal of Portfolio Management.
* Wilder, J. W. (1978). *New Concepts in Technical Trading Systems* - the
  original definition of ATR, RSI and ADX.
* Liu, Y., Tsyvinski, A. (2021). *Risks and Returns of Cryptocurrency*. Review
  of Financial Studies - evidence on momentum in crypto specifically.
