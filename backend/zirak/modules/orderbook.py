"""Order-book intelligence: spread, depth near the mid, bid/ask imbalance, large "walls", and a fair
Toman price of USDT implied by BTCTMN / BTCUSDT and ETHTMN / ETHUSDT.

Numbers are for display and analysis, so floats are fine here (no money moves). In replay mode the
book is synthetic (built from candles) and the response says so.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from zirak.i18n import fa_num, fa_pct
from zirak.models import BookLevel, OrderBook


@dataclass(frozen=True)
class Wall:
    side: str  # "bid" | "ask"
    price: float
    qty: float
    distance_pct: float  # from the mid
    size_x_median: float  # how many times the median level size


@dataclass(frozen=True)
class BookStats:
    symbol: str
    mid: float
    spread_pct: float
    bid_depth_1pct: float  # base quantity within 1 % below the mid
    ask_depth_1pct: float
    imbalance_pct: float  # +: more bids than asks within 1 %
    walls: list[Wall] = field(default_factory=list)
    synthetic: bool = False
    summary_fa: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _depth(levels: list[BookLevel], mid: float, pct: float, side: str) -> float:
    if side == "bid":
        return sum(float(lv.qty) for lv in levels if float(lv.price) >= mid * (1 - pct / 100))
    return sum(float(lv.qty) for lv in levels if float(lv.price) <= mid * (1 + pct / 100))


def _walls(levels: list[BookLevel], mid: float, side: str, within_pct: float, factor: float) -> list[Wall]:
    near = [lv for lv in levels if abs(float(lv.price) / mid - 1) * 100 <= within_pct]
    if len(near) < 4:
        return []
    med = statistics.median(float(lv.qty) for lv in near)
    if med <= 0:
        return []
    return [
        Wall(
            side,
            float(lv.price),
            float(lv.qty),
            round((float(lv.price) / mid - 1) * 100, 3),
            round(float(lv.qty) / med, 1),
        )
        for lv in near
        if float(lv.qty) >= factor * med
    ]


def analyse(book: OrderBook, within_pct: float = 3.0, wall_factor: float = 5.0) -> BookStats:
    bid, ask = book.best_bid, book.best_ask
    if bid is None or ask is None or bid <= 0:
        raise ValueError("book needs both sides")
    mid = float((bid + ask) / 2)
    spread = float(ask - bid) / mid * 100
    bd, ad = _depth(book.bids, mid, 1, "bid"), _depth(book.asks, mid, 1, "ask")
    imb = (bd - ad) / (bd + ad) * 100 if bd + ad > 0 else 0.0
    walls = _walls(book.bids, mid, "bid", within_pct, wall_factor) + _walls(
        book.asks, mid, "ask", within_pct, wall_factor
    )
    walls.sort(key=lambda w: -w.size_x_median)
    parts = [f"اسپرد {fa_pct(spread, 3)}"]
    if imb > 15:
        parts.append(f"خریداران نزدیک قیمت {fa_pct(imb, 0)} قوی‌ترند")
    elif imb < -15:
        parts.append(f"فروشندگان نزدیک قیمت {fa_pct(-imb, 0)} قوی‌ترند")
    else:
        parts.append("خرید و فروش نزدیک قیمت تقریباً متعادل است")
    if walls:
        w = walls[0]
        kind = "دیوار خرید (حمایت احتمالی)" if w.side == "bid" else "دیوار فروش (مقاومت احتمالی)"
        parts.append(
            f"{kind} در {fa_num(w.price, 2)} به اندازهٔ {fa_num(w.size_x_median, 1)} برابر سفارش معمول"
        )
    return BookStats(
        book.symbol,
        mid,
        round(spread, 4),
        round(bd, 8),
        round(ad, 8),
        round(imb, 2),
        walls[:6],
        book.synthetic,
        "؛ ".join(parts) + ".",
    )


@dataclass(frozen=True)
class FairUsdt:
    market_mid: float | None  # USDTTMN mid
    implied: dict[str, float]  # "BTC" -> BTCTMN mid / BTCUSDT mid
    fair: float | None  # average of the implied prices
    premium_pct: float | None  # +: USDTTMN trades above the implied fair price
    summary_fa: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fair_usdt(mids: dict[str, float | None]) -> FairUsdt:
    """`mids` maps symbols (USDTTMN, BTCTMN, BTCUSDT, ETHTMN, ETHUSDT) to their mid prices."""
    implied: dict[str, float] = {}
    for asset in ("BTC", "ETH"):
        tmn, usdt = mids.get(f"{asset}TMN"), mids.get(f"{asset}USDT")
        if tmn and usdt:
            implied[asset] = tmn / usdt
    fair = sum(implied.values()) / len(implied) if implied else None
    mkt = mids.get("USDTTMN")
    premium = (mkt / fair - 1) * 100 if mkt and fair else None
    if premium is None:
        text = "دادهٔ کافی برای محاسبهٔ قیمت منصفانهٔ تتر نیست."
    elif abs(premium) < 0.3:
        text = f"قیمت تتر ({fa_num(mkt or 0, 0)} تومان) با قیمت ضمنی از بیت‌کوین و اتریوم هم‌خوان است."
    else:
        word = "گران‌تر" if premium > 0 else "ارزان‌تر"
        text = (
            f"تتر در بازار {fa_pct(abs(premium), 2)} {word} از قیمت ضمنی آن "
            f"({fa_num(fair or 0, 0)} تومان) معامله می‌شود."
        )
    return FairUsdt(
        mkt,
        {k: round(v, 2) for k, v in implied.items()},
        round(fair, 2) if fair else None,
        round(premium, 3) if premium is not None else None,
        text,
    )


# ---- API ---------------------------------------------------------------------------------------
router = APIRouter()


@router.get("/fair-usdt")
async def fair_usdt_endpoint(request: Request) -> dict[str, Any]:
    state = request.app.state.zirak
    mids: dict[str, float | None] = {}
    for sym in ("USDTTMN", "BTCTMN", "BTCUSDT", "ETHTMN", "ETHUSDT"):
        if await state.market(sym) is None:
            continue
        try:
            book = await state.book(sym)
        except Exception:
            continue
        mids[sym] = float(book.mid) if book.mid is not None else None
    return fair_usdt(mids).to_dict()


@router.get("/{symbol}")
async def book_endpoint(symbol: str, request: Request) -> dict[str, Any]:
    state = request.app.state.zirak
    if await state.market(symbol) is None:
        raise HTTPException(404, "بازار پیدا نشد")
    try:
        return analyse(await state.book(symbol)).to_dict()
    except ValueError as e:
        raise HTTPException(422, "دفتر سفارش خالی است") from e
