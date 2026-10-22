"""Feature engine: one row per closed candle, computed only from that candle and earlier ones.

These features feed both the explainable setup scanners (setups.py) and the ML meta-labeler
(model.py). They are scale-free (returns, ratios, z-scores) so one model can be trained across
markets. Floats are fine here: features are analysis values, not money.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from zirak.indicators import atr, candles_to_df, ema, rsi
from zirak.models import Candle

#: model inputs (the setup one-hot columns are added in model.py)
FEATURES: tuple[str, ...] = (
    "ret_1",
    "ret_4",
    "ret_16",
    "ret_96",
    "rsi_14",
    "bb_pctb",
    "bb_width",
    "atr_pct",
    "atr_ratio",
    "ema20_gap",
    "ema50_gap",
    "ema200_gap",
    "ema50_slope",
    "vol_z",
    "dist_high_96",
    "dist_low_96",
    "efficiency_48",
    "basis_pct",
    "basis_dev",
    "catchup_4",
    "hour_sin",
    "hour_cos",
)

#: candles needed before every feature is defined
WARMUP_BARS = 210


def implied_closes(series: dict[str, list[Candle]], symbol: str) -> pd.Series | None:
    """For a Toman market XTMN: XUSDT close x USDTTMN close per candle time (the cross rate), or None."""
    if not symbol.endswith("TMN") or symbol == "USDTTMN":
        return None
    base = symbol[: -len("TMN")]
    usd, rate = series.get(f"{base}USDT"), series.get("USDTTMN")
    if not usd or not rate:
        return None
    a = pd.Series([float(c.close) for c in usd], index=[c.ts for c in usd])
    b = pd.Series([float(c.close) for c in rate], index=[c.ts for c in rate])
    out = (a * b).dropna()
    return out if len(out) else None


def feature_frame(candles: list[Candle], implied: pd.Series | None = None) -> pd.DataFrame:
    """Columns: ts, open, high, low, close, volume, the indicator helpers used by setups, and FEATURES.

    `implied` (see `implied_closes`) adds the cross-rate features: `basis_pct` = how far this Toman market
    trades from BTCUSDT x USDTTMN, `basis_dev` = that gap minus its own 24-candle mean, `catchup_4` = the
    cross rate's 4-candle return minus this market's (positive = this market lags and may catch up).
    Without it those features are NaN (USDT markets, USDTTMN, coins without a USDT pair).
    """
    df = candles_to_df(candles)
    if df.empty:
        return df
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    logc = np.log(close)
    for n in (1, 4, 16, 96):
        df[f"ret_{n}"] = (logc - logc.shift(n)) * 100
    df["rsi_14"] = rsi(close, 14)
    mid = close.rolling(20, min_periods=20).mean()
    sd = close.rolling(20, min_periods=20).std(ddof=0)
    df["bb_mid"], df["bb_lower"], df["bb_upper"] = mid, mid - 2 * sd, mid + 2 * sd
    width = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
    df["bb_pctb"] = (close - df["bb_lower"]) / width
    df["bb_width"] = width / mid * 100
    df["atr"] = atr(df, 14)
    df["atr_pct"] = df["atr"] / close * 100
    df["atr_ratio"] = df["atr_pct"] / df["atr_pct"].rolling(96, min_periods=20).median()
    for n in (20, 50, 200):
        e = ema(close, n)
        df[f"ema{n}"] = e
        df[f"ema{n}_gap"] = (close / e - 1) * 100
    df["ema50_slope"] = (df["ema50"] / df["ema50"].shift(8) - 1) * 100
    lv = np.log1p(vol)
    df["vol_z"] = (lv - lv.rolling(96, min_periods=20).mean()) / lv.rolling(96, min_periods=20).std(ddof=0)
    df["high_96"] = high.rolling(96, min_periods=20).max()
    df["low_96"] = low.rolling(96, min_periods=20).min()
    df["high_48_prev"] = high.shift(1).rolling(48, min_periods=20).max()
    df["dist_high_96"] = (close / df["high_96"] - 1) * 100
    df["dist_low_96"] = (close / df["low_96"] - 1) * 100
    move = (close - close.shift(48)).abs()
    path = close.diff().abs().rolling(48, min_periods=48).sum()
    df["efficiency_48"] = move / path.replace(0, np.nan)
    if implied is not None:
        imp = pd.Series(implied.reindex(pd.DatetimeIndex(df["ts"])).to_numpy(dtype=float), index=df.index)
        df["basis_pct"] = (close / imp - 1) * 100
        df["basis_dev"] = df["basis_pct"] - df["basis_pct"].rolling(24, min_periods=12).mean()
        li = pd.Series(np.log(imp.to_numpy(dtype=float)), index=df.index)
        df["catchup_4"] = ((li - li.shift(4)) * 100) - df["ret_4"]
    else:
        df["basis_pct"] = df["basis_dev"] = df["catchup_4"] = np.nan
    hours = df["ts"].dt.hour + df["ts"].dt.minute / 60
    df["hour_sin"] = np.sin(2 * np.pi * hours / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hours / 24)
    return df.replace([np.inf, -np.inf], np.nan)


def row_features(df: pd.DataFrame, i: int) -> dict[str, float]:
    """The model features of row `i` as plain floats (NaN for undefined)."""
    return {f: float(df[f].to_numpy(dtype=float)[i]) for f in FEATURES}
