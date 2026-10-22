"""Setup scanners: explainable, deterministic *candidate* trades (long only: spot can't short).

A setup never trades by itself. Each candidate carries its own exits (take-profit, stop-loss and a time
limit, all from ATR so they scale with volatility) and a Persian reason. The ML meta-labeler then
decides whether this particular candidate is worth taking (model.py), the posture agent may restrict
setups per market (posture.py), and the risk layer sizes it (portfolio.py).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from zirak.i18n import fa_num, fa_pct

SETUPS: tuple[str, ...] = ("mean_reversion", "trend_pullback", "breakout", "basis_reversion")
SETUP_FA = {
    "basis_reversion": "جاماندن از نرخ جهانی",
    "mean_reversion": "بازگشت به میانگین",
    "trend_pullback": "اصلاح در روند صعودی",
    "breakout": "شکست سقف با حجم",
}


@dataclass(frozen=True)
class SetupParams:
    tp_atr: float
    sl_atr: float
    max_bars: int


DEFAULT_SETUP_PARAMS: dict[str, SetupParams] = {
    "mean_reversion": SetupParams(tp_atr=2.0, sl_atr=2.0, max_bars=16),
    "trend_pullback": SetupParams(tp_atr=2.5, sl_atr=1.5, max_bars=24),
    "breakout": SetupParams(tp_atr=3.0, sl_atr=1.5, max_bars=24),
    # tp/sl here are multiples of the cross-rate gap, not of ATR (see scan)
    "basis_reversion": SetupParams(tp_atr=1.5, sl_atr=1.5, max_bars=6),
}


@dataclass
class Candidate:
    symbol: str
    setup: str
    ts: datetime  # open time of the signal candle (decided at its close)
    index: int  # row in the feature frame
    price: float  # close of the signal candle (reference only; fills happen later)
    tp_pct: float  # take-profit distance from entry, %
    sl_pct: float  # stop-loss distance from entry, %
    max_bars: int  # time stop
    reason_fa: str
    indicators: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


def _ok(*values: float) -> bool:
    return all(not (isinstance(v, float) and math.isnan(v)) for v in values)


def scan(
    df: pd.DataFrame,
    i: int,
    symbol: str,
    min_tp_pct: float,
    params: dict[str, SetupParams] | None = None,
    enabled: tuple[str, ...] = SETUPS,
) -> list[Candidate]:
    """Candidates at row `i` (a closed candle). `min_tp_pct` keeps targets well above trading costs."""
    p = params or DEFAULT_SETUP_PARAMS
    r = df.iloc[i]
    close, low, atr_pct = float(r["close"]), float(r["low"]), float(r["atr_pct"])
    rsi_v, pctb = float(r["rsi_14"]), float(r["bb_pctb"])
    if not _ok(close, atr_pct, rsi_v, pctb) or atr_pct <= 0:
        return []
    ind = {
        "close": close,
        "rsi_14": round(rsi_v, 2),
        "bb_pctb": round(pctb, 3),
        "atr_pct": round(atr_pct, 3),
        "ema20": float(r["ema20"]),
        "ema50": float(r["ema50"]),
        "ema200": float(r["ema200"]),
        "vol_z": round(float(r["vol_z"]), 2) if _ok(float(r["vol_z"])) else 0.0,
        "ret_96": round(float(r["ret_96"]), 2) if _ok(float(r["ret_96"])) else 0.0,
    }
    out: list[Candidate] = []

    def add(setup: str, reason: str, unit: float | None = None) -> None:
        sp = p[setup]
        u = atr_pct if unit is None else unit
        tp = max(sp.tp_atr * u, min_tp_pct)
        sl = min(max(sp.sl_atr * u, 0.6), 4.0)
        out.append(
            Candidate(
                symbol,
                setup,
                r["ts"].to_pydatetime(),
                i,
                close,
                round(tp, 4),
                round(sl, 4),
                sp.max_bars,
                f"{SETUP_FA[setup]}: {reason} هدف سود {fa_pct(tp, 2)}، حد ضرر {fa_pct(sl, 2)}.",
                dict(ind),
            )
        )

    dev, catch = float(r["basis_dev"]), float(r["catchup_4"])
    if "basis_reversion" in enabled and _ok(dev, catch) and dev <= -0.35 and catch > 0:
        ind["basis_dev"], ind["catchup_4"] = round(dev, 3), round(catch, 3)
        add(
            "basis_reversion",
            f"این بازار تومانی {fa_pct(-dev, 2)} ارزان‌تر از نرخ معمولش نسبت به «قیمت جهانی × نرخ تتر» است و "
            "نرخ ضمنی در ۴ کندل اخیر جلوتر رفته؛ انتظار داریم فاصله بسته شود.",
            unit=abs(dev),
        )
    ret96 = float(r["ret_96"])
    if "mean_reversion" in enabled and pctb < 0 and rsi_v < 32 and _ok(ret96) and ret96 > -12:
        add(
            "mean_reversion",
            f"قیمت زیر باند پایین بولینگر بسته شد و RSI به {fa_num(rsi_v, 0)} رسید (اشباع فروش)، "
            "بدون اینکه بازار در سقوط آزاد باشد.",
        )
    e20, e50, e200, slope = float(r["ema20"]), float(r["ema50"]), float(r["ema200"]), float(r["ema50_slope"])
    if (
        "trend_pullback" in enabled
        and _ok(e20, e50, e200, slope)
        and close > e50 > e200
        and slope > 0
        and low <= e20 * 1.002
        and close > e20
        and 40 <= rsi_v <= 60
    ):
        add(
            "trend_pullback",
            "میانگین ۵۰ بالای میانگین ۲۰۰ و رو به بالاست؛ قیمت تا میانگین ۲۰ اصلاح کرد و دوباره بالای آن بسته شد.",
        )
    prev_high, vol_z = float(r["high_48_prev"]), float(r["vol_z"])
    eff, atr_ratio = float(r["efficiency_48"]), float(r["atr_ratio"])
    if (
        "breakout" in enabled
        and _ok(prev_high, vol_z, eff, atr_ratio)
        and close > prev_high
        and vol_z > 1.0
        and eff > 0.25
        and atr_ratio < 2.5
    ):
        add(
            "breakout",
            f"قیمت بالای سقف ۴۸ کندل قبل بسته شد و حجم {fa_num(vol_z, 1)} انحراف معیار بالاتر از معمول بود.",
        )
    return out
