"""Vectorised, strictly causal technical indicators.

Every function here uses only information available up to and including the
current bar. Nothing shifts data backwards in time, which is what makes the
backtester free of look-ahead bias.

The indicators are deliberately plain pandas/numpy so they can be unit tested
without any external technical-analysis dependency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing (the classic RSI/ATR/ADX average)."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rolling_std(series: pd.Series, period: int) -> pd.Series:
    """Rolling standard deviation (population)."""
    return series.rolling(window=period, min_periods=period).std(ddof=0)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Wilder true range."""
    previous_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average true range."""
    return _wilder(true_range(high, low, close), period)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative strength index (Wilder)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)
    result = pd.Series(np.nan, index=close.index, dtype="float64")
    valid = avg_gain.notna() & avg_loss.notna()
    denominator = (avg_gain + avg_loss).where(valid)
    with np.errstate(divide="ignore", invalid="ignore"):
        computed = 100.0 * avg_gain / denominator
    result[valid] = computed[valid]
    # Flat market (no gains and no losses) is neutral by convention.
    result[valid & (denominator == 0)] = 50.0
    return result


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Average directional index. Returns (adx, plus_di, minus_di)."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )
    atr_values = _wilder(true_range(high, low, close), period)
    safe_atr = atr_values.replace(0.0, np.nan)
    plus_di = 100.0 * _wilder(plus_dm, period) / safe_atr
    minus_di = 100.0 * _wilder(minus_dm, period) / safe_atr
    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    return _wilder(dx, period), plus_di, minus_di


def bollinger_bands(
    close: pd.Series, period: int = 20, std_multiplier: float = 2.0
) -> pd.DataFrame:
    """Bollinger bands with bandwidth and %B."""
    middle = sma(close, period)
    deviation = rolling_std(close, period)
    upper = middle + std_multiplier * deviation
    lower = middle - std_multiplier * deviation
    width = upper - lower
    safe_middle = middle.replace(0.0, np.nan)
    safe_width = width.replace(0.0, np.nan)
    return pd.DataFrame(
        {
            "bb_middle": middle,
            "bb_upper": upper,
            "bb_lower": lower,
            "bb_bandwidth": width / safe_middle,
            "bb_percent_b": (close - lower) / safe_width,
        }
    )


def donchian_channel(
    high: pd.Series, low: pd.Series, period: int = 20, shift: int = 1
) -> pd.DataFrame:
    """Donchian channel.

    shift=1 (the default) is what removes look-ahead bias: the breakout level
    for bar t is computed from bars t-period .. t-1 and therefore never
    contains the very bar that is being tested for a breakout.
    """
    upper = high.rolling(window=period, min_periods=period).max().shift(shift)
    lower = low.rolling(window=period, min_periods=period).min().shift(shift)
    return pd.DataFrame(
        {
            "donchian_upper": upper,
            "donchian_lower": lower,
            "donchian_middle": (upper + lower) / 2.0,
        }
    )


def zscore(series: pd.Series, period: int = 20) -> pd.Series:
    """Rolling z-score: how many standard deviations away from the mean."""
    mean = sma(series, period)
    deviation = rolling_std(series, period).replace(0.0, np.nan)
    return (series - mean) / deviation


def rate_of_change(series: pd.Series, period: int = 10) -> pd.Series:
    """Momentum as a fraction (0.05 means +5 percent over the period)."""
    previous = series.shift(period).replace(0.0, np.nan)
    return series / previous - 1.0


def realized_volatility(
    close: pd.Series, period: int = 20, periods_per_year: float = 365 * 24 * 4
) -> pd.Series:
    """Annualised realised volatility from log returns."""
    log_returns = np.log(close / close.shift(1))
    return log_returns.rolling(window=period, min_periods=period).std(ddof=0) * np.sqrt(
        periods_per_year
    )


def rolling_vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 20
) -> pd.Series:
    """Rolling volume weighted average price over the last N candles."""
    typical_price = (high + low + close) / 3.0
    weighted = (typical_price * volume).rolling(window=period, min_periods=period).sum()
    total_volume = volume.rolling(window=period, min_periods=period).sum().replace(0.0, np.nan)
    return weighted / total_volume


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """Current volume divided by its rolling average."""
    average = sma(volume, period).replace(0.0, np.nan)
    return volume / average


def highest(series: pd.Series, period: int, shift: int = 0) -> pd.Series:
    """Rolling maximum, optionally shifted to exclude the current bar."""
    return series.rolling(window=period, min_periods=period).max().shift(shift)


def lowest(series: pd.Series, period: int, shift: int = 0) -> pd.Series:
    """Rolling minimum, optionally shifted to exclude the current bar."""
    return series.rolling(window=period, min_periods=period).min().shift(shift)


def slope_pct(series: pd.Series, period: int = 10) -> pd.Series:
    """Percentage change of a series over the last N bars."""
    return rate_of_change(series, period)


def percentile_rank(series: pd.Series, period: int = 100) -> pd.Series:
    """Rolling percentile rank of the latest value within its own history.

    Returns a value in [0, 1]. Used by the regime engine to decide whether the
    current volatility is unusually low or unusually high for this market.
    """

    def _rank(window: np.ndarray) -> float:
        current = window[-1]
        if np.isnan(current):
            return np.nan
        valid = window[~np.isnan(window)]
        if valid.size == 0:
            return np.nan
        return float((valid <= current).sum()) / float(valid.size)

    return series.rolling(window=period, min_periods=max(10, period // 5)).apply(_rank, raw=True)


def crossed_above(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True on the bar where fast crosses above slow."""
    return (fast > slow) & (fast.shift(1) <= slow.shift(1))


def crossed_below(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True on the bar where fast crosses below slow."""
    return (fast < slow) & (fast.shift(1) >= slow.shift(1))


def safe_float(value: object, default: float | None = None) -> float | None:
    """Convert numpy/pandas scalars to plain floats, mapping NaN to default."""
    try:
        if value is None:
            return default
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if np.isnan(number) or np.isinf(number):
        return default
    return number


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Moving average convergence divergence."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame(
        {
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": macd_line - signal_line,
        }
    )


def keltner_channels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
) -> pd.DataFrame:
    """Keltner channels: an EMA surrounded by an ATR band."""
    middle = ema(close, ema_period)
    band = atr(high, low, close, atr_period) * multiplier
    return pd.DataFrame(
        {
            "keltner_middle": middle,
            "keltner_upper": middle + band,
            "keltner_lower": middle - band,
        }
    )


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    """SuperTrend: an ATR trailing stop that flips with the trend.

    The band is stateful (each bar depends on the previous one), so this is a
    loop rather than a vectorised expression. It only ever reads bars up to the
    current one, so it stays causal.
    """
    atr_values = atr(high, low, close, period)
    median_price = (high + low) / 2.0
    upper_basic = median_price + multiplier * atr_values
    lower_basic = median_price - multiplier * atr_values

    length = len(close)
    line = np.full(length, np.nan)
    direction = np.full(length, np.nan)
    upper = np.full(length, np.nan)
    lower = np.full(length, np.nan)

    closes = close.to_numpy(dtype="float64")
    upper_values = upper_basic.to_numpy(dtype="float64")
    lower_values = lower_basic.to_numpy(dtype="float64")

    started = False
    for index in range(length):
        if np.isnan(upper_values[index]) or np.isnan(lower_values[index]):
            continue
        if not started:
            upper[index] = upper_values[index]
            lower[index] = lower_values[index]
            direction[index] = 1.0
            line[index] = lower[index]
            started = True
            continue

        previous = index - 1
        previous_upper = upper[previous] if not np.isnan(upper[previous]) else upper_values[index]
        previous_lower = lower[previous] if not np.isnan(lower[previous]) else lower_values[index]

        upper[index] = (
            min(upper_values[index], previous_upper)
            if closes[previous] <= previous_upper
            else upper_values[index]
        )
        lower[index] = (
            max(lower_values[index], previous_lower)
            if closes[previous] >= previous_lower
            else lower_values[index]
        )

        if closes[index] > upper[index]:
            direction[index] = 1.0
        elif closes[index] < lower[index]:
            direction[index] = -1.0
        else:
            direction[index] = direction[previous]

        line[index] = lower[index] if direction[index] > 0 else upper[index]

    return pd.DataFrame(
        {
            "supertrend": pd.Series(line, index=close.index),
            "supertrend_direction": pd.Series(direction, index=close.index),
        }
    )


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
) -> pd.DataFrame:
    """Ichimoku Kinko Hyo.

    The two cloud lines are shifted FORWARD by kijun_period, which is what the
    original system does: the cloud visible at bar t was computed from data at
    bar t - kijun_period. Shifting forward therefore never leaks future data.
    """
    tenkan = (highest(high, tenkan_period) + lowest(low, tenkan_period)) / 2.0
    kijun = (highest(high, kijun_period) + lowest(low, kijun_period)) / 2.0
    senkou_a = ((tenkan + kijun) / 2.0).shift(kijun_period)
    senkou_b = ((highest(high, senkou_b_period) + lowest(low, senkou_b_period)) / 2.0).shift(
        kijun_period
    )
    return pd.DataFrame(
        {
            "tenkan": tenkan,
            "kijun": kijun,
            "senkou_a": senkou_a,
            "senkou_b": senkou_b,
            "cloud_top": pd.concat([senkou_a, senkou_b], axis=1).max(axis=1),
            "cloud_bottom": pd.concat([senkou_a, senkou_b], axis=1).min(axis=1),
        }
    )


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    """Stochastic oscillator (%K and %D)."""
    highest_high = highest(high, k_period)
    lowest_low = lowest(low, k_period)
    span = (highest_high - lowest_low).replace(0.0, np.nan)
    percent_k = 100.0 * (close - lowest_low) / span
    return pd.DataFrame(
        {
            "stoch_k": percent_k,
            "stoch_d": percent_k.rolling(window=d_period, min_periods=d_period).mean(),
        }
    )
