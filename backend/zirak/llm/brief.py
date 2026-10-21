"""Persian market brief. Facts are computed deterministically; the LLM (if any) only phrases them."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from zirak.i18n import fa_num, fa_pct
from zirak.indicators import atr, candles_to_df, ema, last, rsi
from zirak.llm.provider import LLMProvider
from zirak.markets import ASSET_NAMES_FA, market_name_fa
from zirak.models import Candle, Market, OrderBook


@dataclass(frozen=True)
class MarketFacts:
    symbol: str
    name_fa: str
    price: float
    change_24h_pct: float
    trend: str  # "up" | "down" | "range"
    ema20: float | None
    ema50: float | None
    rsi14: float | None
    volatility_pct: float | None  # ATR(14) as % of price
    volatility: str  # "low" | "medium" | "high"
    support: float
    resistance: float
    book_imbalance_pct: float | None  # +: more bids than asks within 1% of mid
    spread_pct: float | None
    book_synthetic: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_facts(market: Market, candles: list[Candle], book: OrderBook | None) -> MarketFacts:
    """`candles` should be 1h candles, oldest first (at least ~60 for meaningful values)."""
    if not candles:
        raise ValueError("no candles")
    df = candles_to_df(candles[-300:])
    close = df["close"]
    price = float(close.iloc[-1])
    e20, e50 = last(ema(close, 20)), last(ema(close, 50))
    e50_prev = last(ema(close, 50).iloc[:-6]) if len(close) > 56 else None
    if e20 and e50 and e50_prev:
        if price > e20 > e50 and e50 > e50_prev:
            trend = "up"
        elif price < e20 < e50 and e50 < e50_prev:
            trend = "down"
        else:
            trend = "range"
    else:
        trend = "range"
    a = last(atr(df, 14))
    vol_pct = a / price * 100 if a else None
    vol = "medium" if vol_pct is None else "low" if vol_pct < 0.5 else "high" if vol_pct > 1.2 else "medium"
    look = df.tail(48)
    ref = float(close.iloc[-25]) if len(close) > 24 else float(close.iloc[0])
    imbalance = spread = None
    if book is not None and book.mid is not None:
        mid = float(book.mid)
        bids = sum(float(lv.qty) for lv in book.bids if float(lv.price) >= mid * 0.99)
        asks = sum(float(lv.qty) for lv in book.asks if float(lv.price) <= mid * 1.01)
        if bids + asks > 0:
            imbalance = (bids - asks) / (bids + asks) * 100
        if book.best_ask is not None and book.best_bid is not None:
            spread = float(book.best_ask - book.best_bid) / mid * 100
    return MarketFacts(
        symbol=market.symbol,
        name_fa=market_name_fa(market),
        price=price,
        change_24h_pct=(price / ref - 1) * 100,
        trend=trend,
        ema20=e20,
        ema50=e50,
        rsi14=last(rsi(close, 14)),
        volatility_pct=vol_pct,
        volatility=vol,
        support=float(look["low"].min()),
        resistance=float(look["high"].max()),
        book_imbalance_pct=imbalance,
        spread_pct=spread,
        book_synthetic=bool(book.synthetic) if book is not None else True,
    )


TREND_FA = {"up": "صعودی", "down": "نزولی", "range": "خنثی (رنج)"}
VOL_FA = {"low": "کم", "medium": "متوسط", "high": "زیاد"}


def template_brief(f: MarketFacts, market: Market) -> str:
    """Deterministic Persian brief, used with MOCK_LLM=true or if the LLM fails."""
    quote = ASSET_NAMES_FA.get(market.quote, market.quote)
    dec = 0 if market.quote == "TMN" else 2
    parts = [
        f"قیمت فعلی {f.name_fa}: {fa_num(f.price, dec)} {quote}؛ تغییر ۲۴ ساعت: {fa_pct(f.change_24h_pct)}.",
        f"روند کوتاه‌مدت {TREND_FA[f.trend]} است"
        + (
            f" (قیمت نسبت به میانگین ۲۰ و ۵۰ کندل {'بالاتر' if f.trend == 'up' else 'پایین‌تر'} است)."
            if f.trend != "range"
            else "؛ میانگین‌ها جهت مشخصی ندارند."
        ),
    ]
    if f.volatility_pct is not None:
        parts.append(
            f"نوسان {VOL_FA[f.volatility]} است (میانگین دامنهٔ هر کندل حدود {fa_pct(f.volatility_pct, 2)})."
        )
    if f.rsi14 is not None:
        state = "بیش‌خرید" if f.rsi14 > 70 else "بیش‌فروش" if f.rsi14 < 30 else "عادی"
        parts.append(f"RSI برابر {fa_num(f.rsi14, 0)} و در محدودهٔ {state} است.")
    parts.append(f"حمایت نزدیک: {fa_num(f.support, dec)} — مقاومت نزدیک: {fa_num(f.resistance, dec)}.")
    if f.book_imbalance_pct is not None:
        side = "خریداران" if f.book_imbalance_pct > 0 else "فروشندگان"
        note = " (دفتر سفارش شبیه‌سازی‌شده)" if f.book_synthetic else ""
        parts.append(
            f"در دفتر سفارش، {side} حدود {fa_pct(abs(f.book_imbalance_pct), 0)} دست بالا را دارند{note}."
        )
    parts.append("این تحلیل خودکار است و توصیهٔ مالی نیست.")
    return " ".join(parts)


SYSTEM_PROMPT = (
    "You are Zirak, a careful crypto market analyst. Write a short market brief in fluent Persian "
    "(4-6 sentences) for a retail user, using ONLY the facts in the JSON. Do not invent numbers or news. "
    "Use Persian digits. Mention trend, volatility, order-book imbalance and key levels. "
    "Do not give buy/sell advice. End with: «این تحلیل خودکار است و توصیهٔ مالی نیست.»"
)


async def market_brief(llm: LLMProvider, market: Market, facts: MarketFacts) -> tuple[str, str]:
    """Returns (brief_fa, source) where source is the provider name or "template"."""
    text = await llm.chat(SYSTEM_PROMPT, json.dumps(facts.to_dict(), ensure_ascii=False))
    if text and text.strip():
        return text.strip(), llm.name
    return template_brief(facts, market), "template"
