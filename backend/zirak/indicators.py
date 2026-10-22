"""Technical indicators on pandas Series of floats.

Indicators are *analysis* values, so floats are fine here; money (orders, balances) stays Decimal.
All functions only use data up to each row (no look-ahead).
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd

from zirak.models import Candle


class Columns(Protocol):
    """Anything with named float columns: a pandas DataFrame or a strategy `Frame`."""

    def __getitem__(self, name: str) -> pd.Series: ...


def candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    n = len(candles)
    cols = np.empty((5, n), dtype=float)
    for i, c in enumerate(candles):
        cols[0, i], cols[1, i], cols[2, i] = float(c.open), float(c.high), float(c.low)
        cols[3, i], cols[4, i] = float(c.close), float(c.volume)
    return pd.DataFrame(
        {
            "ts": pd.DatetimeIndex([c.ts for c in candles]) if n else pd.DatetimeIndex([], tz="UTC"),
            "open": cols[0],
            "high": cols[1],
            "low": cols[2],
            "close": cols[3],
            "volume": cols[4],
        }
    )


def ema(series: pd.Series, period: int) -> pd.Series:
    """EMA identical to pandas `ewm(span=period, adjust=False, min_periods=period)`, computed with a
    plain loop (far cheaper than pandas on the short windows strategies use)."""
    x = series.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) == 0:
        return pd.Series(out, index=series.index)
    a = 2.0 / (period + 1)
    y = x[0]
    for i in range(len(x)):
        y = x[i] if i == 0 else a * x[i] + (1 - a) * y
        if i >= period - 1:
            out[i] = y
    return pd.Series(out, index=series.index)


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI (numpy loop: much faster than chained pandas ewm on short windows)."""
    x = series.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) <= period:
        return pd.Series(out, index=series.index)
    d = np.diff(x)
    gains, losses = np.clip(d, 0, None), np.clip(-d, 0, None)
    avg_g, avg_l = gains[:period].mean(), losses[:period].mean()
    for i in range(period, len(x)):
        if i > period:
            avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
            avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return pd.Series(out, index=series.index)


def atr(df: Columns, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def pct_change_from_high(df: Columns, lookback: int) -> pd.Series:
    """% distance of the close from the highest high of the last `lookback` candles (incl. this one)."""
    high = df["high"].rolling(lookback, min_periods=1).max()
    return (df["close"] / high - 1) * 100


def pct_change_from_low(df: Columns, lookback: int) -> pd.Series:
    low = df["low"].rolling(lookback, min_periods=1).min()
    return (df["close"] / low - 1) * 100


def last(series: pd.Series) -> float | None:
    """Last value as float, or None if missing/NaN."""
    if series.empty:
        return None
    v = series.iloc[-1]
    return None if pd.isna(v) else float(v)
