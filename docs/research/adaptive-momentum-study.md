# Adaptive Momentum - research study

**Verdict: FAILED.** The strategy does not have positive expectancy after
realistic trading costs, on any market or parameter set tested. Do not trade it
with real money in this form.

> Study run on 2026-08-24: 622,080 candles, 9 markets, 24 months, 17,144
> simulated trades. Everything below is reproducible from the repository.

This page records what was tested, what was found and why, including the two
backtester bugs the study exposed. Everything here can be reproduced with:

```bash
cd backend
.venv/Scripts/python.exe scripts/download_history.py --months 24 --timeframe 15m
.venv/Scripts/python.exe scripts/run_research.py --strategy adaptive_momentum
```

---

## 1. Study design

| | |
| --- | --- |
| Strategy | `adaptive_momentum` (Adaptive EMA + RSI + ATR Momentum Day Trader) |
| Timeframe | 15m entries, 1h trend filter |
| Markets | BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK (all /USDT perpetual) |
| Period | 2024-09-03 to 2026-08-24, 24 months, 69,120 candles per market |
| Total data | 622,080 candles |
| Split | 60 percent in-sample / 20 percent validation / 20 percent out-of-sample, chronological, never shuffled |
| Costs | taker 0.05 percent, slippage 0.05 percent, funding 0.01 percent per 8h |
| Risk | 0.5 percent per trade, 3x leverage, 2 percent daily loss limit, max 3 concurrent positions |

Parameters were chosen on the in-sample block only. The validation and
out-of-sample windows were never used to make a choice.

The account drawdown circuit breaker was raised from 15 to 95 percent **for the
study only**. At 15 percent the simulation halts partway through and every
losing configuration gets truncated at the same number, which makes comparison
impossible. The production configuration keeps it at 15 percent.

---

## 2. Baseline result

Default parameters, full 24 months, per market:

| Market | Return | Profit factor | Sharpe | Max DD | Trades | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USDT | -91.2% | 0.63 | -8.48 | 91.2% | 1,628 | 30.3% |
| ETH/USDT | -95.0% | 0.65 | -8.45 | 95.0% | 2,493 | 30.7% |
| SOL/USDT | -95.0% | 0.68 | -8.18 | 95.0% | 2,659 | 32.2% |
| BNB/USDT | -92.9% | 0.59 | -8.44 | 93.0% | 1,855 | 30.2% |
| XRP/USDT | -95.0% | 0.65 | -8.25 | 95.0% | 2,578 | 32.4% |
| DOGE/USDT | -94.9% | 0.74 | -7.61 | 94.9% | 3,002 | 32.5% |
| ADA/USDT | -95.0% | 0.71 | -7.84 | 95.0% | 2,860 | 32.1% |
| AVAX/USDT | -94.9% | 0.73 | -7.68 | 94.9% | 2,885 | 32.3% |
| LINK/USDT | -95.0% | 0.68 | -8.38 | 95.0% | 2,487 | 30.9% |
| **Portfolio** | **-100.0%** | **0.61** | **-8.10** | **100.0%** | **17,144** | **31.2%** |

The result is consistent across nine independent markets. That consistency is
itself informative: this is not one market behaving badly, it is the strategy.

Trade frequency is roughly 3 to 4 per market per day, which is inside the
1 to 5 range the specification asked for. The problem is not the number of
trades. It is what each one is worth.

---

## 3. Why it fails

The decisive test is running the identical strategy with all costs set to zero:

| Cost assumption | Win rate | Avg win | Avg loss | Expectancy | Return |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Zero costs** | 38.8% | +1.02R | -0.62R | **+0.016R** | +12.7% |
| Real costs (0.05 + 0.05) | 30.3% | +1.03R | -0.77R | **-0.226R** | -91.2% |

**The raw signal has a small positive edge of about +0.016R per trade. The
round trip costs about 0.24R. Costs are roughly fifteen times the edge.**

Where 0.24R comes from: risk per trade is 0.5 percent of equity and the stop is
1.5 ATR, which on BTC 15m is roughly 0.6 percent of price. Position notional is
therefore about 0.83 times equity, and a 0.20 percent round trip on that
notional is 0.166 percent of equity — a third of the 0.5 percent risked. Every
trade starts a third of an R in the hole.

A 31 percent win rate needs better than 2.2R average winners to break even
before costs. The strategy delivers about 1.0R, because the 1.5 ATR trailing
stop closes 73 percent of trades before the 2R target is reached.

### Exit model comparison (BTC, 24 months, real costs)

| Model | Trades | Win rate | Avg win | Avg loss | Expectancy |
| --- | ---: | ---: | ---: | ---: | ---: |
| ATR trailing (default) | 1,628 | 30.3% | +1.03R | -0.77R | -0.226R |
| Pure 2R target, no trailing | 1,342 | 30.6% | +1.84R | -1.16R | -0.247R |
| EMA exit | 1,440 | 25.5% | +1.65R | -0.90R | -0.253R |

The trailing stop caps winners at about 1R but also cuts losers to 0.77R, and
is marginally the best of the three. None of them is close to positive.

Note the average loss of 1.16R without trailing: a stop does not fill at the
stop price. Slippage makes the realised loss larger than 1R, which is one more
reason the arithmetic does not work at this stop distance.

---

## 3b. Validation and out-of-sample

Parameters were selected on the in-sample block alone. These two windows were
never used to make any choice.

| Window | Return | Profit factor | Sharpe | Max DD | Trades | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Validation (20%) | -96.8% | 0.56 | -9.47 | 97.1% | 3,262 | 31.0% |
| Out-of-sample (20%) | -96.9% | 0.54 | -9.24 | 97.2% | 2,951 | 29.5% |

Out-of-sample, per market — every one of the nine loses:

| Market | Return | Profit factor | Max DD | Trades | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USDT | -37.6% | 0.47 | 37.7% | 243 | 25.1% |
| ETH/USDT | -46.3% | 0.58 | 46.7% | 415 | 30.4% |
| SOL/USDT | -40.0% | 0.67 | 41.3% | 440 | 30.5% |
| BNB/USDT | -16.6% | 0.81 | 17.5% | 211 | 33.6% |
| XRP/USDT | -40.9% | 0.63 | 45.0% | 408 | 31.9% |
| DOGE/USDT | -50.0% | 0.60 | 50.4% | 492 | 32.3% |
| ADA/USDT | -48.7% | 0.65 | 49.0% | 571 | 31.7% |
| AVAX/USDT | -51.2% | 0.58 | 51.9% | 471 | 28.0% |
| LINK/USDT | -53.4% | 0.60 | 53.4% | 535 | 30.1% |

The tuned and baseline rows are identical because **the search selected
nothing**. Ten parameter axes were swept on the in-sample block and not one
candidate on any axis passed the acceptance gates (at least 30 trades, drawdown
at or below 35 percent, profit factor above 1.0, positive Sharpe). The
optimiser therefore kept the baseline, which is the correct behaviour: there
was nothing better to choose.

That is worth stating plainly. **Fifty-one configurations were tested on
in-sample data and none of them was acceptable, so nothing was carried forward
to be validated.** A tuning result was never reached, because there was nothing
to tune towards.

---


---

## 3c. Walk-forward, Monte Carlo, stability, benchmarks

### Walk-forward (4 rolling folds, 70 percent in-sample per fold)

| Market | Folds | Profitable folds | Avg out-of-sample return | Avg out-of-sample Sharpe |
| --- | ---: | ---: | ---: | ---: |
| BTC/USDT | 4 | **0** | -11.9% | -7.32 |
| ETH/USDT | 4 | **0** | -18.7% | -9.17 |

Zero profitable folds out of eight. The failure is not a single bad period.

### Monte Carlo — 10,000 bootstrap resamples of the out-of-sample trades

| | |
| --- | ---: |
| Median return | -96.99% |
| 5th percentile | -100.00% (account wiped) |
| 95th percentile | -81.67% |
| **Probability of profit** | **0.0%** |
| Median max drawdown | 97.4% |
| Worst max drawdown | 100.0% |
| Median losing streak | 20 trades |
| Worst losing streak | 45 trades |
| Risk of ruin | 38.5% |

Not one simulation in ten thousand ended in profit. When a strategy's edge is
negative, reshuffling the trades cannot rescue it — which is exactly what this
test is for.

### Parameter stability (BTC, in-sample, metric = profit factor)

| Parameter | Values tested | Profit factor across the sweep | Verdict |
| --- | --- | --- | --- |
| `min_signal_score` | 60, 65, 70, 75, 80 | 0.63, 0.63, 0.65, 0.65, 0.64 | stable |
| `atr_stop_multiplier` | 1.2, 1.3, 1.5, 1.7, 2.0 | 0.60, 0.64, 0.65, 0.64, 0.65 | stable |
| `take_profit_r` | 1.5 to 3.0 | 0.59, 0.64, 0.65, 0.65, 0.66, 0.65 | stable |
| `ema_fast` | 16, 18, 20, 22, 24 | 0.65, 0.65, 0.65, 0.65, 0.65 | stable |

**Read this carefully.** "Stable" here does not mean good. It means the result
barely moves whatever you do — the strategy is reliably and uniformly losing
around a profit factor of 0.65. There is no overfitting risk in these
parameters because there is no peak to overfit to.

That is genuinely useful information: it rules out "we just picked bad
parameters" as an explanation.

### Benchmarks, same out-of-sample window

| | Return | Sharpe | Max DD | Trades |
| --- | ---: | ---: | ---: | ---: |
| **Buy and hold BTC** | **+17.7%** | **1.26** | 29.7% | 1 |
| **Buy and hold ETH** | **+20.2%** | **1.16** | 38.3% | 1 |
| adaptive_momentum | -96.9% | -9.24 | 97.2% | 2,951 |
| trend_following | -87.1% | n/a | 88.8% | 1,819 |
| mean_reversion | -56.8% | n/a | 57.6% | 494 |
| macd_momentum | -81.1% | n/a | 83.5% | 1,608 |

The market rose 18 to 20 percent during this window and every active strategy
lost heavily. Doing nothing beat all of them by a wide margin on both raw and
risk-adjusted terms.

The other three strategies were run at the same day-trading cost assumptions
and 15m timeframe, which is not what they were designed for, so this table
should not be read as a verdict on them. It is a verdict on trading this
frequently against these costs.

### Cost sensitivity (BTC, out-of-sample)

| Slippage | Return | Profit factor | Trades |
| ---: | ---: | ---: | ---: |
| 0.02% | -29.8% | 0.60 | 249 |
| 0.05% | -37.6% | 0.47 | 243 |
| 0.10% | -48.6% | 0.33 | 240 |
| 0.15% | -55.8% | 0.26 | 236 |

**Verdict: FRAGILE.** The result degrades monotonically with the cost
assumption and is negative at every level, including the most optimistic one.
## 4. What would have to change

Each of these was tested on BTC over the full 24 months. All remain negative.

| Variant | Trades | Expectancy | Return |
| --- | ---: | ---: | ---: |
| Baseline: 1.5 ATR stop, 0.05 + 0.05 costs | 1,628 | -0.226R | -91.2% |
| 3.0 ATR stop | 1,529 | -0.106R | -67.1% |
| 4.0 ATR stop | 1,527 | -0.078R | -55.7% |
| Signal score 85 with a 3.0 ATR stop | 1,168 | -0.110R | -58.0% |
| Costs 0.02 + 0.02 (VIP fees, patient entries) | 1,681 | -0.082R | -61.7% |
| 3.0 ATR stop **and** 0.02 + 0.02 costs | 1,561 | **-0.034R** | -32.6% |

Widening the stop works in the direction the arithmetic predicts: it lowers the
position notional for the same risk, so cost per R falls from 0.24 to about
0.09. Lower fees help for the same reason. But the best combination of both is
still **-0.034R per trade**, because the underlying edge is only +0.016R.

Raising the score threshold does not help. Filtering harder removes trades in
roughly equal proportion from winners and losers, which is what you would
expect if the score is not actually ranking trade quality.

**There is no parameter setting that rescues this strategy.** The gap is not a
tuning problem, it is an order-of-magnitude problem.

---

## 5. Two backtester bugs this study exposed

Both made the backtester disagree with the live engine, and both were found by
running the study rather than by reading the code.

### The consecutive-loss counter was never reset

The live Risk Engine reads the losing streak from that day's statistics row, so
it starts at zero every UTC day. The backtester incremented it forever, so
after the first three losing trades it blocked every further entry for the rest
of the run.

The first baseline reported 3 to 6 trades per market over two years. DOGE, AVAX
and LINK each took exactly three trades, lost all three, and then went silent —
that pattern is what gave it away. After the fix, BTC goes from 5 trades to
112, and once the drawdown halt is also lifted for the study, to 1,628.

The post-loss cooldown was missing from the backtester entirely, so it would
re-enter immediately after a stop while the live engine waits. Both engines now
apply the same rule.

### The portfolio simulator added up separate accounts

Each market is simulated on its own 10,000 account. Summing those PnL figures
made nine accounts losing 90 percent each look like one account losing 519
percent, which is not a possible outcome.

Trades are now replayed in R-multiples — how many times the risked amount they
returned — and applied to one shared, compounding account at the portfolio's
own risk per trade.

This also mattered for the search: an impossible drawdown failed the objective's
drawdown gate for every candidate, so the optimiser would have silently
rejected everything and reported the baseline as the winner while looking like
it had done its job.

Regression tests now cover all three behaviours.

---

## 6. Honest limitations of this study

* **Two years, one market regime family.** 2024-2026 is a specific period. A
  strategy that fails here could behave differently elsewhere, though a
  -0.2R per trade cost gap is not a regime artefact.
* **Candle data, not tick data.** Intrabar sequencing is assumed: when both the
  stop and the target sit inside one candle, the stop is assumed to hit first.
* **Fixed funding rate.** Real funding varies; the study uses a constant
  0.01 percent per 8 hours.
* **Slippage is a flat percentage.** Real slippage depends on order book depth
  and is worse exactly when a breakout strategy wants to trade.
* **No partial take-profits.** The specification asked for scaling out at 1R
  and 2R. That is not implemented, because implementing it only in the
  backtester would break the parity with live execution that makes these
  numbers meaningful at all. It is listed in the roadmap.
* **The portfolio simulation is an approximation.** Signals were generated
  without knowledge of the portfolio state, so a trade the portfolio refused
  would in reality have freed capacity for a later one.

---

## 7. Is it the strategy, or is it 15m day trading?

The same logic run on 1h candles with a 4h trend filter, 24 months, real costs:

| Market | Timeframe | Trades | Expectancy | Profit factor | Return |
| --- | --- | ---: | ---: | ---: | ---: |
| BTC/USDT | 15m | 1,628 | -0.226R | 0.63 | -91.2% |
| BTC/USDT | 1h | 1,424 | -0.135R | 0.73 | -73.6% |
| ETH/USDT | 15m | 2,493 | -0.172R | 0.65 | -95.0% |
| ETH/USDT | 1h | 1,320 | -0.078R | 0.83 | -54.4% |
| SOL/USDT | 15m | 2,659 | -0.162R | 0.68 | -95.0% |
| SOL/USDT | 1h | 1,015 | -0.076R | 0.82 | -42.4% |

And the same 1h runs with costs set to zero, to isolate the raw signal:

| Market | Trades | Expectancy | Profit factor | Return |
| --- | ---: | ---: | ---: | ---: |
| BTC/USDT | 1,435 | **+0.026R** | 1.06 | +18.3% |
| ETH/USDT | 1,326 | **+0.037R** | 1.09 | +26.0% |
| SOL/USDT | 1,024 | **+0.016R** | 1.04 | +7.1% |

Two things follow, and they matter more than any single number above.

**The signal is not noise.** At zero cost it is positive on every market and on
both timeframes tested, with profit factors between 1.04 and 1.09. There is a
real, small momentum effect here.

**The edge is an order of magnitude too small to pay for trading it.** Moving
from 15m to 1h roughly halves the cost drag, because each trade captures a
larger move for the same number of round trips. It is not nearly enough: the
edge is about 0.03R and the cost is about 0.11R even at 1h.

This is the honest shape of the result. The specification is not badly
designed — the components do what they claim. Intraday momentum on liquid
crypto perpetuals, traded with taker orders at 0.05 percent plus slippage,
simply does not clear the bar.

---

## 8. What would make this worth revisiting

In rough order of how much each would move the number:

1. **Maker entries instead of taker.** Posting limit orders at the breakout
   level rather than crossing the spread removes most of the 0.10 percent
   round trip. This changes the fill model, not the signal, and would need
   partial-fill handling in the execution engine.
2. **A higher timeframe.** 4h and daily were not tested here. The 15m to 1h
   comparison shows the direction is right.
3. **A genuinely stronger filter.** The signal score does not currently rank
   trade quality: filtering harder removes winners and losers in equal
   proportion. A component that actually separates them would change the
   arithmetic; adjusting the threshold on the existing seven will not.
4. **Wider stops with the same account risk.** Mechanical, already measured:
   3 ATR instead of 1.5 ATR cuts cost per R by about 60 percent.

What would **not** help: more parameter tuning on the current seven components.
Ten axes were swept and none produced an acceptable configuration on
in-sample data, let alone out of sample.

---

## 9. Final report, in the requested format

### FINAL STRATEGY

| | |
| --- | --- |
| Strategy | Adaptive EMA + RSI + ATR Momentum Day Trader (`adaptive_momentum`) |
| Timeframe | 15m |
| Trend timeframe | 1h (EMA50 / EMA200, hard gate) |
| EMA | 20 / 50 on 15m |
| RSI | 14, long band 52-72, short band 28-48 |
| ADX | 14, minimum 20 |
| ATR | 14, stop 1.5x |
| Volume | SMA 20, minimum 1.20x |
| VWAP | rolling 48 |
| Entry rules | Score at or above 70/100 from seven components, with the 1h trend as a hard gate |
| Exit rules | ATR trailing stop (best of the three tested), or the 2R target, or the stop |
| Stop loss | 1.5 x ATR(14) |
| Take profit | 2.0 R |
| Trailing stop | 1.5 x ATR |
| Risk per trade | 0.5% of equity |
| Max portfolio risk | 1.5% |
| Max positions | 3, max 2 per correlation group |
| Leverage | 3x isolated |
| Daily loss limit | 2% (3% emergency) |
| Cooldown | 45 minutes after a loss |

**These are the specified parameters, unchanged.** The optimiser was given ten
axes and 51 configurations on in-sample data and found nothing acceptable to
replace them with.

### PERFORMANCE — full 24 months, portfolio

| | |
| --- | ---: |
| Total return | -100.0% |
| Annualised return | not meaningful (account wiped) |
| Sharpe | -8.10 |
| Sortino | negative on every market |
| Profit factor | 0.61 |
| Win rate | 31.2% |
| Average win | +1.03R |
| Average loss | -0.77R |
| Expectancy | **-0.226R per trade** |
| Max drawdown | 100.0% |
| Total trades | 17,144 |

### OUT-OF-SAMPLE

| | |
| --- | ---: |
| Return | -96.9% |
| Sharpe | -9.24 |
| Profit factor | 0.54 |
| Max drawdown | 97.2% |
| Trades | 2,951 |
| Markets profitable | **0 of 9** |

### WALK-FORWARD

| Market | Folds | Profitable | Avg return | Avg Sharpe |
| --- | ---: | ---: | ---: | ---: |
| BTC/USDT | 4 | 0 | -11.9% | -7.32 |
| ETH/USDT | 4 | 0 | -18.7% | -9.17 |

### MONTE CARLO (10,000 simulations)

Median -96.99%, 5th percentile -100.00%, 95th percentile -81.67%, median
drawdown 97.4%, worst drawdown 100.0%, expected losing streak 20 trades (worst
45), probability of profit **0.0%**, risk of ruin 38.5%.

### PARAMETER STABILITY

All four swept parameters are stable, in the sense that the result barely
changes across their range. None shows a spike, so none carries overfitting
risk. They are stable around a profit factor of 0.65, which is stably losing.

### FINAL CONFIG

`config/adaptive_momentum.yaml` holds the exact configuration tested. It is
provided so the study can be reproduced, **not as a recommendation to trade
it.**

---

## 10. Verdict against the acceptance criteria

| Criterion | Target | Result | Pass |
| --- | --- | --- | :---: |
| Profit factor | > 1.20 | 0.54 out of sample | NO |
| Sharpe | > 1.0 | -9.24 | NO |
| Sortino | > 1.2 | negative | NO |
| Expectancy | > 0 | -0.226R | NO |
| Max drawdown | as low as possible | 97% | NO |
| Out-of-sample profit | positive | -96.9% | NO |
| Walk-forward consistency | consistent | 0 of 8 folds profitable | NO |
| Monte Carlo | acceptable | 0.0% chance of profit | NO |
| Trade count | statistically sufficient | 17,144 | YES |
| Positive after fees and slippage | required | negative at every cost level | NO |

**Nine of ten criteria fail. The strategy is rejected.**

The one criterion it passes — trade count — is what makes the rejection
trustworthy: with 17,144 trades this is not a small-sample accident.

## 11. What was NOT done, and why

* **Partial take-profits (30% at 1R, 40% at 2R, trail the rest).** Not
  implemented. Adding it to the backtester alone would break parity with live
  execution, and parity is the only reason these numbers mean anything. It
  would have to be built in both engines together, and it would not close a
  0.2R per trade gap.
* **Order book depth and spread filters.** The liquidity filter uses 24h
  volume; real depth and spread were not modelled.
* **A brute-force parameter grid.** Deliberately avoided. A coordinate sweep
  over ten axes was used instead, which produces the stability data as a
  by-product and cannot fit thousands of combinations to noise.
* **4h and daily timeframes.** Only 15m and 1h were compared. The direction of
  the 15m to 1h result suggests higher timeframes are where to look next.
