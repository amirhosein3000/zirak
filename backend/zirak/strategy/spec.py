"""StrategySpec: the validated JSON format the LLM strategy builder must produce, and RuleStrategy which
runs it deterministically. The LLM can only describe rules from this small vocabulary; it never trades.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from zirak.i18n import fa_num, fa_pct
from zirak.indicators import ema, last, pct_change_from_high, pct_change_from_low, rsi
from zirak.markets import ASSET_NAMES_FA, DEFAULT_MARKETS
from zirak.models import HUNDRED, RESOLUTION_SECONDS, Side
from zirak.strategy.base import Signal, Strategy, StrategyContext

# Persian labels for the visual builder: what each condition means and which fields it takes.
CONDITION_FA: dict[str, dict[str, Any]] = {
    "drop_from_high": {"title_fa": "ریزش از سقف اخیر", "fields": ["pct", "minutes"]},
    "rise_from_low": {"title_fa": "رشد از کف اخیر", "fields": ["pct", "minutes"]},
    "rsi_below": {"title_fa": "RSI کمتر از", "fields": ["value", "period"]},
    "rsi_above": {"title_fa": "RSI بیشتر از", "fields": ["value", "period"]},
    "ema_cross_up": {"title_fa": "تقاطع صعودی میانگین‌ها", "fields": ["fast", "slow"]},
    "ema_cross_down": {"title_fa": "تقاطع نزولی میانگین‌ها", "fields": ["fast", "slow"]},
    "price_below": {"title_fa": "قیمت پایین‌تر از", "fields": ["value"]},
    "price_above": {"title_fa": "قیمت بالاتر از", "fields": ["value"]},
}

SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}(TMN|USDT)$")


def window_fa(minutes: int) -> str:
    """۳۰ دقیقه / ۲ ساعت / ۳ روز."""
    if minutes % 1440 == 0:
        return f"{fa_num(minutes // 1440, 0)} روز"
    if minutes % 60 == 0:
        return f"{fa_num(minutes // 60, 0)} ساعت"
    return f"{fa_num(minutes, 0)} دقیقه"


ConditionKind = Literal[
    "drop_from_high",  # close is >= pct % below the highest high of the last `lookback` candles
    "rise_from_low",  # close is >= pct % above the lowest low of the last `lookback` candles
    "rsi_below",
    "rsi_above",
    "ema_cross_up",
    "ema_cross_down",
    "price_below",
    "price_above",
]

RESOLUTION_FA = {"5m": "۵ دقیقه‌ای", "15m": "۱۵ دقیقه‌ای", "1h": "یک‌ساعته", "4h": "چهارساعته", "1d": "روزانه"}


class Condition(BaseModel):
    kind: ConditionKind
    pct: float | None = Field(None, gt=0, le=90)
    lookback: int | None = Field(None, ge=2, le=2000)
    minutes: int | None = Field(None, ge=1, le=43200)  # time window; the spec turns it into `lookback`
    value: float | None = Field(None, gt=0)
    period: int | None = Field(None, ge=2, le=200)
    fast: int | None = Field(None, ge=2, le=200)
    slow: int | None = Field(None, ge=3, le=400)

    @model_validator(mode="after")
    def _check_fields(self) -> Condition:
        k = self.kind
        if k in ("drop_from_high", "rise_from_low"):
            if self.pct is None:
                raise ValueError(f"{k} needs pct")
            self.lookback = self.lookback or 24
        elif k in ("rsi_below", "rsi_above"):
            if self.value is None or not 0 < self.value < 100:
                raise ValueError(f"{k} needs value between 0 and 100")
            self.period = self.period or 14
        elif k in ("ema_cross_up", "ema_cross_down"):
            self.fast, self.slow = self.fast or 12, self.slow or 26
            if self.fast >= self.slow:
                raise ValueError("fast must be smaller than slow")
        elif k in ("price_below", "price_above") and self.value is None:
            raise ValueError(f"{k} needs value")
        return self

    @property
    def warmup(self) -> int:
        return max(self.lookback or 0, (self.period or 0) + 2, (self.slow or 0) + 2, 2)

    def describe_fa(self, asset_fa: str) -> str:
        k = self.kind
        if k in ("drop_from_high", "rise_from_low") and self.minutes:
            word = "پایین بیاید" if k == "drop_from_high" else "بالا برود"
            ref = "سقف" if k == "drop_from_high" else "کف"
            return (
                f"قیمت {asset_fa} در {window_fa(self.minutes)} اخیر حداقل {fa_pct(self.pct or 0)} "
                f"از {ref} همان بازه {word}"
            )
        if k == "drop_from_high":
            return (
                f"قیمت {asset_fa} نسبت به بالاترین قیمت {fa_num(self.lookback or 0, 0)} کندل اخیر "
                f"حداقل {fa_pct(self.pct or 0)} پایین بیاید"
            )
        if k == "rise_from_low":
            return (
                f"قیمت {asset_fa} نسبت به پایین‌ترین قیمت {fa_num(self.lookback or 0, 0)} کندل اخیر "
                f"حداقل {fa_pct(self.pct or 0)} بالا برود"
            )
        if k == "rsi_below":
            return f"RSI ({fa_num(self.period or 14, 0)}) زیر {fa_num(self.value or 0, 0)} باشد"
        if k == "rsi_above":
            return f"RSI ({fa_num(self.period or 14, 0)}) بالای {fa_num(self.value or 0, 0)} باشد"
        if k == "ema_cross_up":
            return f"میانگین {fa_num(self.fast or 0, 0)} از میانگین {fa_num(self.slow or 0, 0)} بالاتر برود"
        if k == "ema_cross_down":
            return f"میانگین {fa_num(self.fast or 0, 0)} زیر میانگین {fa_num(self.slow or 0, 0)} برود"
        if k == "price_below":
            return f"قیمت {asset_fa} به زیر {fa_num(self.value or 0)} برسد"
        return f"قیمت {asset_fa} به بالای {fa_num(self.value or 0)} برسد"

    def evaluate(self, ctx: StrategyContext) -> tuple[bool, dict[str, float]]:
        df, k = ctx.df, self.kind
        if k == "drop_from_high":
            v = last(pct_change_from_high(df, self.lookback or 24))
            return (v is not None and v <= -(self.pct or 0)), {"change_from_high_pct": v or 0.0}
        if k == "rise_from_low":
            v = last(pct_change_from_low(df, self.lookback or 24))
            return (v is not None and v >= (self.pct or 0)), {"change_from_low_pct": v or 0.0}
        if k in ("rsi_below", "rsi_above"):
            v = last(rsi(df["close"], self.period or 14))
            if v is None:
                return False, {}
            ok = v < (self.value or 0) if k == "rsi_below" else v > (self.value or 0)
            return ok, {f"rsi{self.period}": v}
        if k in ("ema_cross_up", "ema_cross_down"):
            f, s = ema(df["close"], self.fast or 12), ema(df["close"], self.slow or 26)
            vals = [last(f), last(s), last(f.iloc[:-1]), last(s.iloc[:-1])]
            if any(v is None for v in vals):
                return False, {}
            fn, sn, fp, sp = (float(v) for v in vals if v is not None)
            ok = (fp <= sp and fn > sn) if k == "ema_cross_up" else (fp >= sp and fn < sn)
            return ok, {f"ema{self.fast}": fn, f"ema{self.slow}": sn}
        close = ctx.close
        ok = close <= (self.value or 0) if k == "price_below" else close >= (self.value or 0)
        return ok, {"close": close}


class StrategySpec(BaseModel):
    version: Literal[1] = 1
    name: str = Field("استراتژی من", max_length=80)
    symbol: str
    resolution: Literal["5m", "15m", "1h", "4h", "1d"] = "1h"
    entry: list[Condition] = Field(min_length=1, max_length=5)  # all must hold (AND)
    exit: list[Condition] = Field(default_factory=list, max_length=5)  # any triggers a full exit (OR)
    position_size_pct: float = Field(10, gt=0, le=100)
    take_profit_pct: float | None = Field(None, gt=0, le=200)
    stop_loss_pct: float | None = Field(None, gt=0, le=50)
    max_entries: int = Field(1, ge=1, le=20)
    cooldown_candles: int = Field(0, ge=0, le=1000)

    @model_validator(mode="after")
    def _check_symbol(self) -> StrategySpec:
        # Any Wallex-style symbol; the API rejects markets it has no data for.
        if self.symbol not in DEFAULT_MARKETS and not SYMBOL_RE.match(self.symbol):
            raise ValueError(f"unknown market {self.symbol}")
        candle_s = RESOLUTION_SECONDS[self.resolution]
        for c in [*self.entry, *self.exit]:
            if c.minutes and c.kind in ("drop_from_high", "rise_from_low"):
                if c.minutes * 60 < candle_s:
                    raise ValueError("time window is shorter than one candle")
                # the window includes the signal candle: 30 min on 5m candles = the last 6 candles
                c.lookback = min(2000, max(2, math.ceil(c.minutes * 60 / candle_s)))
        return self

    @property
    def warmup(self) -> int:
        return max(c.warmup for c in [*self.entry, *self.exit])

    def describe_fa(self) -> list[str]:
        """Plain-Persian bullet lines the user confirms before anything runs."""
        base, quote_code = split_symbol(self.symbol)
        asset = ASSET_NAMES_FA.get(base, base)
        quote = ASSET_NAMES_FA.get(quote_code, quote_code)
        lines = [f"بازار: {asset} به {quote} — کندل‌های {RESOLUTION_FA[self.resolution]}"]
        conds = " و ".join(c.describe_fa(asset) for c in self.entry)
        lines.append(f"خرید: وقتی {conds}، با {fa_pct(self.position_size_pct, 0)} از سرمایه")
        if self.max_entries > 1:
            lines.append(f"حداکثر {fa_num(self.max_entries, 0)} بار خرید پله‌ای")
        if self.take_profit_pct:
            lines.append(f"فروش با سود: وقتی قیمت {fa_pct(self.take_profit_pct)} بالاتر از میانگین خرید برود")
        if self.stop_loss_pct:
            lines.append(
                f"حد ضرر: اگر قیمت {fa_pct(self.stop_loss_pct)} پایین‌تر از میانگین خرید برود، می‌فروشد"
            )
        for c in self.exit:
            lines.append(f"فروش کامل وقتی {c.describe_fa(asset)}")
        if self.cooldown_candles:
            lines.append(f"بعد از هر فروش، {fa_num(self.cooldown_candles, 0)} کندل صبر می‌کند")
        return lines


class RuleStrategy(Strategy):
    key = "rules"
    title_fa = "استراتژی ساخته‌شده از متن فارسی"
    description_fa = "قوانین ساده‌ای که از توضیح فارسی شما ساخته شده و قبل از اجرا تأیید کرده‌اید."

    def __init__(self, spec: StrategySpec | dict[str, Any], **kw: Any) -> None:
        self.spec = spec if isinstance(spec, StrategySpec) else StrategySpec.model_validate(spec)
        super().__init__(spec=self.spec.model_dump())
        self.warmup = self.spec.warmup

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        if len(ctx.df) < self.warmup:
            return []
        asset = ASSET_NAMES_FA.get(ctx.market.base, ctx.market.base)
        if ctx.in_position:
            for cond in self.spec.exit:
                ok, ind = cond.evaluate(ctx)
                if ok:
                    return [
                        Signal(
                            Side.SELL,
                            HUNDRED,
                            f"rule_exit_{cond.kind}",
                            f"شرط خروج برقرار شد: {cond.describe_fa(asset)}.",
                            {**ind, "close": ctx.close},
                        )
                    ]
        if ctx.entries >= self.spec.max_entries:
            return []
        indicators: dict[str, float] = {"close": ctx.close}
        for cond in self.spec.entry:
            ok, ind = cond.evaluate(ctx)
            indicators.update(ind)
            if not ok:
                return []
        reasons = " و ".join(c.describe_fa(asset) for c in self.spec.entry)
        return [
            Signal(
                Side.BUY,
                Decimal(str(self.spec.position_size_pct)),
                "rule_entry",
                f"شرط خرید برقرار شد: {reasons}.",
                indicators,
            )
        ]


def split_symbol(symbol: str) -> tuple[str, str]:
    m = DEFAULT_MARKETS.get(symbol)
    if m:
        return m.base, m.quote
    quote = "USDT" if symbol.endswith("USDT") else "TMN"
    return symbol[: -len(quote)], quote


def resolution_ok(resolution: str) -> bool:
    return resolution in RESOLUTION_SECONDS
