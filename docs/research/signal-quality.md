# Signal quality: the filter that finally moved expectancy

**Date:** 25 August 2026
**Verdict:** the first validated positive result in this project, with limits.

## The problem it addresses

Every earlier study ended the same way. From
[adaptive-momentum-study.md](adaptive-momentum-study.md):

> At zero cost the strategy is marginally positive (+0.016R per trade). With
> real costs it is -0.226R. The cost is roughly fifteen times the edge.

Adding strategies does not help, because a new strategy pays the same toll. Two
attempts to *select* a better strategy both failed out of sample:

| Selection | In sample | Out of sample |
| --- | --- | --- |
| 19 combinations, winner `trend_following @ 1d` | 62% profitable, +0.089R | 20% profitable, **-0.045R** |
| 74 combinations, 11 passed every gate | best +0.172R | **0 of 11 passed** |

That leaves one lever: take **fewer** signals, so the toll is paid only on the
ones that earn it.

## Method

Every backtest trade now records the measurable conditions at entry — trend,
volatility regime, ADX, ATR %, volatility rank, stop distance, session, and the
strategy's own confidence score. Expectancy is then measured per condition.

Pooled sample: **8,980 trades**, six strategies (`trend_following`,
`breakout_donchian`, `supertrend_follow`, `macd_momentum`, `keltner_trend`,
`ichimoku_trend`) across eight markets on the 1 hour timeframe.

Split by date, never by random sampling:

- in sample: 2 March 2025 – 25 February 2026 (5,659 trades)
- out of sample: 25 February – 24 August 2026 (3,321 trades)

The threshold was chosen on the in-sample half only.

## Result

Confidence was by far the strongest discriminator. Filtering on it:

| Threshold | In-sample expectancy | **Out-of-sample expectancy** | Signals kept |
| ---: | ---: | ---: | ---: |
| none | +0.0159 R | **−0.0203 R** | 100% |
| 0.50 | +0.0199 R | +0.0125 R | 76% |
| 0.65 | +0.0548 R | +0.0240 R | 45% |
| 0.75 | +0.0770 R | **+0.0879 R** | 23% |
| 0.80 | +0.0952 R | **+0.1104 R** | 18% |
| 0.85 | +0.1133 R | **+0.1199 R** | 13% |

Taking every signal loses money out of sample. Taking the top quarter makes it.

Three things make this more credible than the earlier findings:

1. **Monotonic across eight thresholds.** A plateau, not a spike. The earlier
   parameter studies flagged spikes as an overfitting signature; this is the
   opposite shape.
2. **Out-of-sample is as good as or better than in-sample** at every threshold
   from 0.75 up. Overfitting produces the reverse.
3. **It works inside individual strategies**, so it is signal quality rather
   than a disguised strategy selection:

| Strategy | All signals (OOS) | Confidence ≥ 0.75 | |
| --- | ---: | ---: | --- |
| `trend_following` | −0.0431 R | **+0.0740 R** | 339 trades |
| `breakout_donchian` | +0.0394 R | **+0.1203 R** | 287 trades |
| `keltner_trend` | +0.0229 R | **+0.3161 R** | 59 trades |
| `ichimoku_trend` | −0.0544 R | −0.0265 R | 55 trades |
| `supertrend_follow` | +0.0212 R | −0.2641 R | 27 trades — too few |
| `macd_momentum` | −0.0920 R | — | 2 trades — barely scores high |

Four of six improved independently. The two that did not produce almost no
high-confidence signals, so there is nothing to conclude either way.

## What changed

`min_signal_confidence` default: **0.35 → 0.75**.

This affects new installations. An existing configuration keeps whatever it was
set to, because silently changing what a running account trades is not a default's
job.

## What this is not

- **Not a profit guarantee.** +0.088R per trade at 0.5% risk is about +0.044% of
  equity per trade. It is a positive expectancy, not a return forecast.
- **Not tested live.** One timeframe, eight markets, eighteen months, one cost
  model.
- **Not free.** At 0.75 you discard 77% of signals. Fewer trades mean longer idle
  periods and a smaller sample to judge live performance from.
- **Not a reason to raise risk.** A better expectancy with the same risk per
  trade compounds faster; a better expectancy with more risk per trade just
  moves the ruin probability.

## Reproducing it

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_signal_quality.py -q
```

The analysis itself is `app/backtesting/signal_quality.py`; every backtest
result now carries `entry_context` on each trade, which is what it reads.
