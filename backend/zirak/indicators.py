"""Technical indicators on pandas Series of floats.

Indicators are *analysis* values, so floats are fine here; money (orders, balances) stays Decimal.
All functions only use data up to each row (no look-ahead).
"""

from __future__ import annotations

import pandas as pd

from zirak.models import Candle


def candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "ts": [c.ts for c in candles],
            "open": [float(c.open) for c in candles],
            "high": [float(c.high) for c in candles],
            "low": [float(c.low) for c in candles],
            "close": [float(c.close) for c in candles],
            "volume": [float(c.volume) for c in candles],
        }
    )
    return df


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, float("nan"))
    out = 100 - 100 / (1 + rs)
    # No losses in the window means RSI = 100.
    return out.where(loss != 0, 100.0).where(gain.notna())


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def pct_change_from_high(df: pd.DataFrame, lookback: int) -> pd.Series:
    """% distance of the close from the highest high of the last `lookback` candles (incl. this one)."""
    high = df["high"].rolling(lookback, min_periods=1).max()
    return (df["close"] / high - 1) * 100


def pct_change_from_low(df: pd.DataFrame, lookback: int) -> pd.Series:
    low = df["low"].rolling(lookback, min_periods=1).min()
    return (df["close"] / low - 1) * 100


def last(series: pd.Series) -> float | None:
    """Last value as float, or None if missing/NaN."""
    if series.empty:
        return None
    v = series.iloc[-1]
    return None if pd.isna(v) else float(v)
