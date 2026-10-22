"""Portfolio mode: a target allocation across TMN, USDT, BTC and ETH, rebalanced when any weight drifts
more than `threshold_pct` percentage points from its target.

Honest simulation (Decimal money): the decision uses candle t's close, trades execute at candle t+1's
open with slippage, the taker fee is taken from the received asset, quantities respect each market's
precision, and trades below the market minimum are skipped. Sells run before buys so buys are funded.
Compared against holding the initial allocation and against holding only Toman.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from zirak.backtest.metrics import max_drawdown_pct
from zirak.fees import apply_slippage
from zirak.i18n import fa_num, fa_pct
from zirak.markets import ASSET_NAMES_FA
from zirak.models import HUNDRED, ONE, ZERO, Candle, Market, Side, utcnow

QUOTE = "TMN"
ASSETS = ("TMN", "USDT", "BTC", "ETH")


def _fa(asset: str) -> str:
    return ASSET_NAMES_FA.get(asset, asset)


@dataclass
class Trade:
    asset: str
    side: str  # "buy" | "sell" (against TMN)
    qty: Decimal
    price: Decimal
    fee_tmn: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "side": self.side,
            "qty": str(self.qty),
            "price": str(self.price),
            "fee_tmn": str(self.fee_tmn),
        }


@dataclass
class Rebalance:
    ts: datetime
    drift: dict[str, float]  # asset -> weight - target, percentage points, at the decision
    trades: list[Trade] = field(default_factory=list)
    note_fa: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "drift": self.drift,
            "trades": [t.to_dict() for t in self.trades],
            "note_fa": self.note_fa,
        }


def weights(holdings: dict[str, Decimal], prices: dict[str, Decimal]) -> tuple[Decimal, dict[str, Decimal]]:
    values = {a: q * (ONE if a == QUOTE else prices[a]) for a, q in holdings.items()}
    total = sum(values.values(), ZERO)
    return total, {a: (v / total * HUNDRED if total > 0 else ZERO) for a, v in values.items()}


def plan_trades(
    holdings: dict[str, Decimal],
    prices: dict[str, Decimal],
    targets: dict[str, Decimal],
    markets: dict[str, Market],
) -> list[tuple[str, Side, Decimal]]:
    """Orders (asset, side, qty) that move holdings to the targets at `prices`. Sells first."""
    total, _ = weights(holdings, prices)
    out: list[tuple[str, Side, Decimal]] = []
    for a in sorted(targets, key=lambda x: x):
        if a == QUOTE:
            continue
        m = markets[f"{a}{QUOTE}"]
        want = total * targets[a] / HUNDRED / prices[a]
        diff = m.round_qty(abs(want - holdings.get(a, ZERO)))
        side = Side.BUY if want > holdings.get(a, ZERO) else Side.SELL
        if side is Side.SELL:
            diff = min(diff, m.round_qty(holdings.get(a, ZERO)))
        if diff > 0 and m.check_order(diff, prices[a]) is None:
            out.append((a, side, diff))
    out.sort(key=lambda t: 0 if t[1] is Side.SELL else 1)
    return out


def execute(
    holdings: dict[str, Decimal],
    orders: list[tuple[str, Side, Decimal]],
    opens: dict[str, Decimal],
    markets: dict[str, Market],
    taker: Decimal,
    slippage_bps: Decimal,
) -> list[Trade]:
    trades: list[Trade] = []
    for a, side, qty in orders:
        m = markets[f"{a}{QUOTE}"]
        price = apply_slippage(opens[a], side, slippage_bps, m)
        if side is Side.SELL:
            qty = min(qty, m.round_qty(holdings.get(a, ZERO)))
            proceeds = qty * price
            fee = proceeds * taker
            holdings[a] -= qty
            holdings[QUOTE] += proceeds - fee
        else:
            qty = min(qty, m.round_qty(holdings[QUOTE] / price))  # never spend Toman we don't have
            cost = qty * price
            fee = qty * taker  # fee in the received asset
            holdings[QUOTE] -= cost
            holdings[a] = holdings.get(a, ZERO) + qty - fee
            fee = fee * price
        if qty > 0:
            trades.append(Trade(a, side.value, qty, price, fee))
    return trades


def explain(rb: Rebalance, targets: dict[str, Decimal]) -> str:
    worst = max(rb.drift, key=lambda a: abs(rb.drift[a]))
    w = float(targets[worst]) + rb.drift[worst]
    word = "بیشتر" if rb.drift[worst] > 0 else "کمتر"
    parts = [
        f"سهم {_fa(worst)} به {fa_pct(w)} رسید (هدف {fa_pct(float(targets[worst]))})؛ "
        f"{fa_pct(abs(rb.drift[worst]))} {word} از هدف بود."
    ]
    sells = [t for t in rb.trades if t.side == "sell"]
    buys = [t for t in rb.trades if t.side == "buy"]
    if sells:
        parts.append("فروختیم: " + "، ".join(f"{fa_num(t.qty, 6)} {_fa(t.asset)}" for t in sells) + ".")
    if buys:
        parts.append("خریدیم: " + "، ".join(f"{fa_num(t.qty, 6)} {_fa(t.asset)}" for t in buys) + ".")
    parts.append("یعنی بخشی از دارایی‌ای که گران شده را فروختیم و آنچه عقب مانده را خریدیم.")
    return " ".join(parts)


def align(series: dict[str, list[Candle]]) -> list[tuple[datetime, dict[str, Candle]]]:
    """Rows of candles at timestamps present in every series."""
    common = set.intersection(*(set(c.ts for c in s) for s in series.values())) if series else set()
    by = {a: {c.ts: c for c in s} for a, s in series.items()}
    return [(ts, {a: by[a][ts] for a in series}) for ts in sorted(common)]


def backtest(
    series: dict[str, list[Candle]],  # asset -> its {asset}TMN candles
    targets: dict[str, Decimal],
    markets: dict[str, Market],
    initial_tmn: Decimal,
    taker: Decimal,
    slippage_bps: Decimal,
    threshold_pct: Decimal = Decimal(5),
) -> dict[str, Any]:
    if abs(sum(targets.values(), ZERO) - HUNDRED) > Decimal("0.01"):
        raise ValueError("targets must add up to 100")
    rows = align(series)
    if len(rows) < 3:
        raise ValueError("not enough overlapping candles")
    holdings: dict[str, Decimal] = {a: ZERO for a in targets}
    holdings[QUOTE] = initial_tmn
    pending = plan_trades(holdings, {a: c.close for a, c in rows[0][1].items()}, targets, markets)
    rebalances: list[Rebalance] = []
    hold: dict[str, Decimal] | None = None
    curve: list[tuple[datetime, float, float]] = []
    for i in range(1, len(rows)):
        ts, row = rows[i]
        opens = {a: c.open for a, c in row.items()}
        if pending:
            trades = execute(holdings, pending, opens, markets, taker, slippage_bps)
            if rebalances and not rebalances[-1].trades:
                rebalances[-1].trades = trades
                rebalances[-1].note_fa = explain(rebalances[-1], targets)
            pending = []
            if hold is None:
                hold = dict(holdings)  # the "never rebalance" comparison starts from the same first fill
        closes = {a: c.close for a, c in row.items()}
        total, w = weights(holdings, closes)
        hold_total, _ = weights(hold or holdings, closes)
        curve.append((ts, float(total), float(hold_total)))
        drift = {a: float(w.get(a, ZERO) - targets[a]) for a in targets}
        if i < len(rows) - 1 and max(abs(d) for d in drift.values()) > float(threshold_pct):
            pending = plan_trades(holdings, closes, targets, markets)
            if pending:
                rebalances.append(Rebalance(rows[i + 1][0], {a: round(d, 2) for a, d in drift.items()}))
    rebalances = [r for r in rebalances if r.trades]
    eq, hold_eq = [c[1] for c in curve], [c[2] for c in curve]
    fees = sum((t.fee_tmn for r in rebalances for t in r.trades), ZERO)
    start = float(initial_tmn)
    step = max(1, len(curve) // 400)
    return {
        "targets": {a: str(v) for a, v in targets.items()},
        "threshold_pct": str(threshold_pct),
        "period": {"start": rows[0][0].isoformat(), "end": rows[-1][0].isoformat(), "candles": len(rows)},
        "rebalanced": {
            "return_pct": round((eq[-1] / start - 1) * 100, 3),
            "max_drawdown_pct": round(max_drawdown_pct(eq), 3),
        },
        "hold": {
            "return_pct": round((hold_eq[-1] / start - 1) * 100, 3),
            "max_drawdown_pct": round(max_drawdown_pct(hold_eq), 3),
        },
        "toman_only": {"return_pct": 0.0, "max_drawdown_pct": 0.0},
        "rebalances": [r.to_dict() for r in rebalances],
        "fees_tmn": str(fees.quantize(ONE)),
        "final_holdings": {a: str(q) for a, q in holdings.items()},
        "curve": [
            {"ts": c[0].isoformat(), "rebalanced": round(c[1], 2), "hold": round(c[2], 2)}
            for c in curve[::step]
        ],
    }


# ---- API ---------------------------------------------------------------------------------------
router = APIRouter()


class PortfolioIn(BaseModel):
    targets: dict[str, Decimal] = Field(
        default_factory=lambda: {
            "TMN": Decimal(20),
            "USDT": Decimal(30),
            "BTC": Decimal(30),
            "ETH": Decimal(20),
        }
    )
    threshold_pct: Decimal = Field(Decimal(5), gt=0, le=50)
    resolution: str = "1h"
    initial_tmn: Decimal | None = None


async def _inputs(
    state: Any, targets: dict[str, Decimal], resolution: str
) -> tuple[dict[str, list[Candle]], dict[str, Market]]:
    bad = [a for a in targets if a not in ASSETS]
    if bad or not targets:
        raise HTTPException(422, f"دارایی ناشناخته: {', '.join(bad)}")
    series: dict[str, list[Candle]] = {}
    markets: dict[str, Market] = {}
    for a in targets:
        if a == QUOTE:
            continue
        m = await state.market(f"{a}{QUOTE}")
        if m is None:
            raise HTTPException(404, f"بازار {a}{QUOTE} پیدا نشد")
        markets[m.symbol] = m
        series[a] = await state.candles(m.symbol, resolution, 3000)
    return series, markets


@router.post("/backtest")
async def backtest_endpoint(body: PortfolioIn, request: Request) -> dict[str, Any]:
    state = request.app.state.zirak
    s = state.settings
    targets = {a: Decimal(v) for a, v in body.targets.items() if Decimal(v) > 0}
    targets.setdefault(QUOTE, ZERO)
    series, markets = await _inputs(state, targets, body.resolution)
    try:
        return backtest(
            series,
            targets,
            markets,
            body.initial_tmn or s.paper_start_tmn,
            s.fee_taker,
            s.slippage_bps,
            body.threshold_pct,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class SuggestIn(BaseModel):
    targets: dict[str, Decimal]
    holdings: dict[str, Decimal]
    threshold_pct: Decimal = Decimal(5)


@router.post("/suggest")
async def suggest(body: SuggestIn, request: Request) -> dict[str, Any]:
    """What to trade now to get back to the targets (a suggestion only: nothing is executed)."""
    state = request.app.state.zirak
    targets = {a: Decimal(v) for a, v in body.targets.items()}
    targets.setdefault(QUOTE, ZERO)
    series, markets = await _inputs(state, targets, "1h")
    prices = {a: c[-1].close for a, c in series.items() if c}
    holdings = {a: Decimal(body.holdings.get(a, 0)) for a in targets}
    total, w = weights(holdings, prices)
    drift = {a: round(float(w.get(a, ZERO) - targets[a]), 2) for a in targets}
    needed = total > 0 and max(abs(d) for d in drift.values()) > float(body.threshold_pct)
    orders = plan_trades(holdings, prices, targets, markets) if needed else []
    note = (
        "ترکیب سبد شما نزدیک هدف است؛ فعلاً نیازی به متعادل‌سازی نیست."
        if not orders
        else explain(
            Rebalance(utcnow(), drift, [Trade(a, s.value, q, prices[a], ZERO) for a, s, q in orders]),
            targets,
        )
    )
    return {
        "total_tmn": str(total.quantize(ONE)),
        "weights": {a: round(float(v), 2) for a, v in w.items()},
        "drift": drift,
        "orders": [{"asset": a, "side": s.value, "qty": str(q)} for a, s, q in orders],
        "note_fa": note + " این فقط پیشنهاد است و سفارشی ثبت نمی‌شود.",
    }
