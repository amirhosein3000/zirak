"""Market regime detector: trending up / trending down / ranging / volatile, from closed candles only.

- Efficiency ratio (Kaufman) over `lookback` candles: |net move| / sum(|moves|). Near 1 = clean trend,
  near 0 = chop.
- Trend direction from the slope of EMA(50) over the last 10 candles.
- Volatile when ATR(14) as % of price is well above its own recent median (a regime shift, not just
  "crypto is volatile").

`RegimeGated` wraps any strategy so it only opens positions in the regimes you allow (exits are never
blocked). The module's backtest endpoint compares the gated and ungated versions honestly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from zirak.indicators import Columns, atr, ema
from zirak.models import Side
from zirak.strategy.base import Signal, Strategy, StrategyContext

REGIMES = ("trending_up", "trending_down", "ranging", "volatile")
REGIME_FA = {
    "trending_up": "روند صعودی",
    "trending_down": "روند نزولی",
    "ranging": "رنج (نوسان در یک محدوده)",
    "volatile": "پرنوسان و ناآرام",
}
#: which baseline strategies usually suit which regime (shown in the UI as guidance)
SUITS: dict[str, list[str]] = {
    "trending_up": ["ema_cross", "dca"],
    "trending_down": [],
    "ranging": ["rsi_reversion", "grid"],
    "volatile": [],
}
ADVICE_FA = {
    "trending_up": "استراتژی‌های روندی (تقاطع میانگین‌ها) معمولاً در این حالت بهتر کار می‌کنند.",
    "trending_down": "در روند نزولی بهتر است خرید جدید محدود شود یا فقط با حجم کم انجام شود.",
    "ranging": "در بازار رنج، خرید در کف محدوده (RSI یا گرید) معمولاً منطقی‌تر از دنبال‌کردن روند است.",
    "volatile": "نوسان غیرعادی است؛ حجم معاملات را کم کنید و حد ضرر را جدی بگیرید.",
}


@dataclass(frozen=True)
class Regime:
    regime: str
    efficiency: float  # 0..1
    slope_pct: float  # EMA(50) change over the last 10 candles, %
    atr_pct: float  # ATR(14) as % of price
    atr_ratio: float  # ATR% / its median over the window
    label_fa: str
    advice_fa: str
    suits: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify(df: Columns, lookback: int = 48) -> Regime:
    """Classify the regime from the last closed candles (needs at least ~lookback + 20 rows)."""
    close = df["close"]
    n = len(close)
    if n < 30:
        raise ValueError("need at least 30 candles")
    lb = min(lookback, n - 1)
    window = close.iloc[-(lb + 1) :].to_numpy(dtype=float)
    path = float(np.abs(np.diff(window)).sum())
    efficiency = abs(window[-1] - window[0]) / path if path > 0 else 0.0
    e50 = ema(close, 50)
    prev = float(e50.iloc[-11]) if n > 11 else float(e50.iloc[0])
    slope = (float(e50.iloc[-1]) / prev - 1) * 100 if prev else 0.0
    a = atr(df, 14) / close * 100
    atr_now = float(a.iloc[-1]) if not pd.isna(a.iloc[-1]) else 0.0
    median = float(a.iloc[-min(n, 200) :].median()) if a.notna().any() else 0.0
    ratio = atr_now / median if median > 0 else 1.0
    if ratio >= 1.8:
        regime = "volatile"
    elif efficiency >= 0.3 and abs(slope) >= 0.2:
        regime = "trending_up" if slope > 0 else "trending_down"
    else:
        regime = "ranging"
    return Regime(
        regime,
        round(efficiency, 4),
        round(slope, 4),
        round(atr_now, 4),
        round(ratio, 4),
        REGIME_FA[regime],
        ADVICE_FA[regime],
        SUITS[regime],
    )


class RegimeGated(Strategy):
    """Only lets the inner strategy *open* positions in the allowed regimes. Sells always pass."""

    key = "regime_gated"

    def __init__(self, inner: Strategy, allowed: list[str], lookback: int = 48) -> None:
        super().__init__(**inner.params)
        self.inner = inner
        self.allowed = [r for r in allowed if r in REGIMES]
        self.lookback = lookback
        self.warmup = max(inner.warmup, lookback + 20)

    def describe(self) -> dict[str, Any]:
        inner = self.inner.describe()
        only = "، ".join(REGIME_FA[r] for r in self.allowed) or "هیچ حالتی"
        return {**inner, "title_fa": f"{inner['title_fa']} (خرید فقط در {only})", "regimes": self.allowed}

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        signals = self.inner.on_candle(ctx)
        if not any(s.side is Side.BUY for s in signals):
            return signals
        reg = classify(ctx.df, self.lookback)
        if reg.regime in self.allowed:
            return [
                Signal(
                    s.side,
                    s.size_pct,
                    s.reason,
                    s.note_fa,
                    {**s.indicators, "regime_eff": reg.efficiency},
                    s.order_type,
                    s.limit_price,
                )
                for s in signals
            ]
        return [s for s in signals if s.side is not Side.BUY]


# ---- API ---------------------------------------------------------------------------------------
router = APIRouter()


@router.get("/{symbol}")
async def current(symbol: str, request: Request, resolution: str = "1h") -> dict[str, Any]:
    from zirak.indicators import candles_to_df

    state = request.app.state.zirak
    if await state.market(symbol) is None:
        raise HTTPException(404, "بازار پیدا نشد")
    candles = await state.candles(symbol, resolution, 300)
    if len(candles) < 30:
        raise HTTPException(422, "دادهٔ کافی برای تشخیص حالت بازار نیست")
    reg = classify(candles_to_df(candles))
    return {"symbol": symbol, "resolution": resolution, **reg.to_dict()}


class GatedIn(BaseModel):
    symbol: str = "BTCTMN"
    resolution: str = "1h"
    strategy: str = "ema_cross"
    params: dict[str, Any] = Field(default_factory=dict)
    allowed: list[str] = Field(default_factory=lambda: ["trending_up"])


@router.post("/backtest")
async def gated_backtest(body: GatedIn, request: Request) -> dict[str, Any]:
    """Same strategy with and without the regime gate, on the same data, fees included."""
    from zirak.backtest.engine import BacktestSetup, run_backtest_async
    from zirak.engine.risk import RiskConfig
    from zirak.fees import FeeModel
    from zirak.strategy.registry import STRATEGIES, build_strategy

    state = request.app.state.zirak
    s = state.settings
    market = await state.market(body.symbol)
    if market is None or body.strategy not in STRATEGIES:
        raise HTTPException(404, "بازار یا استراتژی پیدا نشد")
    candles = await state.candles(body.symbol, body.resolution, 2200)
    if len(candles) < 200:
        raise HTTPException(422, "دادهٔ کافی نیست")
    out: dict[str, Any] = {}
    for label, strat in (
        ("plain", build_strategy(body.strategy, body.params)),
        ("gated", RegimeGated(build_strategy(body.strategy, body.params), body.allowed)),
    ):
        setup = BacktestSetup(
            market,
            body.resolution,
            strat,
            RiskConfig(),
            FeeModel(s.fee_maker, s.fee_taker),
            s.slippage_bps,
            {"TMN": s.paper_start_tmn, "USDT": s.paper_start_usdt}.get(market.quote, Decimal(1000)),
            s.fill_participation,
        )
        report = await run_backtest_async(candles[100:], setup, warmup=candles[:100])
        out[label] = report["metrics"]
    return {"symbol": body.symbol, "strategy": body.strategy, "allowed": body.allowed, **out}
