"""AI coach: reviews a list of trades (the paper bot, a backtest, the "emotional trader", or trades
you paste) and gives Persian feedback with concrete suggestions.

Every finding is computed deterministically from the trades and candles (so it can be checked); the
LLM, when configured, only rewrites the overall summary. Detected habits:
overtrading, large losses without a stop, chasing pumps, panic selling, averaging down, fee drag,
and cutting winners while letting losers run.
"""

from __future__ import annotations

import bisect
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from zirak.i18n import fa_num, fa_pct
from zirak.llm.provider import LLMProvider
from zirak.models import Candle, ensure_utc


@dataclass(frozen=True)
class TradeIn:
    ts: datetime
    side: str  # "buy" | "sell"
    price: float
    qty: float
    fee_quote: float = 0.0


@dataclass
class Finding:
    code: str
    severity: str  # "high" | "medium" | "low" | "good"
    title_fa: str
    detail_fa: str
    suggestion_fa: str
    examples: list[int] = field(default_factory=list)  # indexes into the trade list


@dataclass(frozen=True)
class RoundTrip:
    entry_ts: datetime
    exit_ts: datetime
    pnl: float
    pnl_pct: float


def round_trips(trades: list[TradeIn]) -> list[RoundTrip]:
    """Average-cost round trips: a position opened by buys and fully or partly closed by sells."""
    qty = cost = 0.0
    opened: datetime | None = None
    out: list[RoundTrip] = []
    for t in trades:
        if t.side == "buy":
            if qty <= 0:
                opened = t.ts
            qty += t.qty
            cost += t.qty * t.price + t.fee_quote
        elif qty > 0:
            q = min(t.qty, qty)
            basis = cost * q / qty
            pnl = q * t.price - t.fee_quote - basis
            out.append(RoundTrip(opened or t.ts, t.ts, pnl, pnl / basis * 100 if basis else 0.0))
            qty -= q
            cost -= basis
    return out


def _close_at(candles: list[Candle], times: list[datetime], ts: datetime, offset_h: float) -> float | None:
    i = bisect.bisect_right(times, ts + timedelta(hours=offset_h)) - 1
    return float(candles[i].close) if 0 <= i < len(candles) else None


def review(trades: list[TradeIn], candles: list[Candle]) -> list[Finding]:
    trades = sorted(trades, key=lambda t: t.ts)
    times = [c.ts for c in candles]
    findings: list[Finding] = []
    if not trades:
        return findings
    days = max((trades[-1].ts - trades[0].ts).total_seconds() / 86400, 1.0)
    per_day = len(trades) / days
    if per_day > 6:
        findings.append(
            Finding(
                "overtrading",
                "high",
                "معامله‌های بیش از حد",
                f"به‌طور میانگین روزی {fa_num(per_day, 1)} معامله انجام شده است؛ هر معامله کارمزد و لغزش دارد.",
                "قبل از هر معامله یک دلیل مشخص بنویسید و برای خودتان سقف تعداد معامله در روز بگذارید.",
            )
        )
    trips = round_trips(trades)
    big = [i for i, r in enumerate(trips) if r.pnl_pct <= -8]
    if big:
        worst = min(trips, key=lambda r: r.pnl_pct)
        findings.append(
            Finding(
                "no_stop_loss",
                "high",
                "زیان‌های بزرگ بدون حد ضرر",
                f"{fa_num(len(big), 0)} معامله با زیان بیش از ۸٪ بسته شده؛ بدترین {fa_pct(worst.pnl_pct)} بود.",
                "برای هر خرید از قبل حد ضرر تعیین کنید (مثلاً ۳ تا ۵٪) و به آن پایبند باشید؛ زیرک این کار را خودکار انجام می‌دهد.",
                big[:5],
            )
        )
    chase = []
    panic = []
    for i, t in enumerate(trades):
        before = _close_at(candles, times, t.ts, -24)
        after = _close_at(candles, times, t.ts, 24)
        if t.side == "buy" and before and t.price / before - 1 >= 0.05:
            chase.append(i)
        if (
            t.side == "sell"
            and before
            and after
            and t.price / before - 1 <= -0.04
            and after / t.price - 1 >= 0.03
        ):
            panic.append(i)
    if chase:
        findings.append(
            Finding(
                "chasing_pumps",
                "medium",
                "خرید بعد از جهش قیمت (ترس از جاماندن)",
                f"{fa_num(len(chase), 0)} خرید بعد از رشد بیش از ۵٪ در ۲۴ ساعت قبل انجام شده است.",
                "به‌جای خرید در اوج هیجان، منتظر اصلاح قیمت بمانید یا خرید را پله‌ای انجام دهید.",
                chase[:5],
            )
        )
    if panic:
        findings.append(
            Finding(
                "panic_selling",
                "medium",
                "فروش هیجانی بعد از ریزش",
                f"{fa_num(len(panic), 0)} بار بعد از ریزش فروخته‌اید و قیمت در ۲۴ ساعت بعد بیش از ۳٪ برگشته است.",
                "حد ضرر را قبل از خرید تعیین کنید تا تصمیم فروش در لحظهٔ ترس گرفته نشود.",
                panic[:5],
            )
        )
    streak, longest, last_buy = 0, 0, None
    for t in trades:
        if t.side == "buy":
            streak = streak + 1 if last_buy is not None and t.price < last_buy else 1
            last_buy = t.price
            longest = max(longest, streak)
        else:
            streak, last_buy = 0, None
    if longest >= 3:
        findings.append(
            Finding(
                "averaging_down",
                "medium",
                "میانگین‌کم‌کردن پشت سر هم",
                f"تا {fa_num(longest, 0)} خرید پیاپی در قیمت‌های پایین‌تر بدون هیچ فروشی انجام شده است.",
                "خرید پله‌ای فقط وقتی منطقی است که از قبل برنامه و سقف کل سرمایه داشته باشد.",
            )
        )
    fees = sum(t.fee_quote for t in trades)
    gross = sum(abs(r.pnl) for r in trips)
    if trips and fees > 0 and gross > 0 and fees / gross >= 0.3:
        findings.append(
            Finding(
                "fee_drag",
                "medium",
                "کارمزد، بخش بزرگی از نتیجه را می‌خورد",
                f"کارمزدها حدود {fa_pct(fees / gross * 100, 0)} از مجموع سود و زیان معامله‌ها است.",
                "معاملات کمتر ولی با دلیل قوی‌تر انجام دهید؛ هدف سود هر معامله باید چند برابر کارمزد رفت‌وبرگشت باشد.",
            )
        )
    wins = [r.pnl_pct for r in trips if r.pnl > 0]
    losses = [-r.pnl_pct for r in trips if r.pnl < 0]
    if len(wins) >= 3 and len(losses) >= 3:
        aw, al = sum(wins) / len(wins), sum(losses) / len(losses)
        if aw < 0.5 * al:
            findings.append(
                Finding(
                    "cut_winners",
                    "medium",
                    "سودها را زود می‌بندید و زیان‌ها را نگه می‌دارید",
                    f"میانگین سود هر معاملهٔ برنده {fa_pct(aw)} و میانگین زیان هر بازنده {fa_pct(al)} است.",
                    "نسبت سود به زیان را حداقل ۱ به ۱ بگذارید (مثلاً حد سود ۴٪ برای حد ضرر ۴٪).",
                )
            )
    if not findings:
        findings.append(
            Finding(
                "disciplined",
                "good",
                "رفتار معاملاتی منظم",
                "الگوی پرخطر مشخصی در این معامله‌ها پیدا نشد.",
                "همین نظم را حفظ کنید و نتیجه را با خرید و نگهداری مقایسه کنید.",
            )
        )
    return findings


def score(findings: list[Finding]) -> int:
    penalty = {"high": 25, "medium": 12, "low": 5, "good": 0}
    return max(0, 100 - sum(penalty[f.severity] for f in findings))


def summary_template(findings: list[Finding], s: int, n: int) -> str:
    bad = [f for f in findings if f.severity != "good"]
    if not bad:
        return f"در {fa_num(n, 0)} معامله، رفتار پرخطری دیده نشد (امتیاز انضباط {fa_num(s, 0)} از ۱۰۰)."
    top = "، ".join(f.title_fa for f in bad[:3])
    return (
        f"در {fa_num(n, 0)} معامله، امتیاز انضباط شما {fa_num(s, 0)} از ۱۰۰ است. مهم‌ترین نکته‌ها: {top}. "
        "این بازخورد آموزشی است و توصیهٔ مالی نیست."
    )


async def coach(trades: list[TradeIn], candles: list[Candle], llm: LLMProvider) -> dict[str, Any]:
    findings = review(trades, candles)
    s = score(findings)
    summary = summary_template(findings, s, len(trades))
    text = await llm.chat(
        "You are a kind, direct trading coach for Iranian retail traders. Rewrite these findings as a short "
        "Persian paragraph (3-4 sentences). Do not add new facts, numbers or predictions. No financial advice.",
        json.dumps([asdict(f) for f in findings], ensure_ascii=False),
    )
    if text:
        summary = text.strip() + " (بازخورد آموزشی است، نه توصیهٔ مالی.)"
    return {
        "score": s,
        "trades": len(trades),
        "summary_fa": summary,
        "findings": [asdict(f) for f in findings],
    }


def trades_from_log(entries: list[dict[str, Any]]) -> list[TradeIn]:
    """Filled entries of a Bot log / backtest report (`trades`)."""
    out = []
    for e in entries:
        filled = float(e.get("filled_qty") or 0)
        if filled <= 0 or not e.get("avg_price"):
            continue
        price = float(e["avg_price"])
        fee = float(e.get("fee") or 0)
        fee_quote = fee * price if e["side"] == "buy" else fee  # buy fees are in base
        out.append(TradeIn(ensure_utc(datetime.fromisoformat(e["ts"])), e["side"], price, filled, fee_quote))
    return out


# ---- API ---------------------------------------------------------------------------------------
router = APIRouter()


class TradeRow(BaseModel):
    ts: datetime
    side: Literal["buy", "sell"]
    price: Decimal = Field(gt=0)
    qty: Decimal = Field(gt=0)
    fee_quote: Decimal = Decimal(0)


class CoachIn(BaseModel):
    source: Literal["bot", "backtest", "trades", "emotional"] = "bot"
    report_id: str | None = None
    symbol: str = "BTCTMN"
    trades: list[TradeRow] = Field(default_factory=list, max_length=5000)


@router.post("")
async def coach_endpoint(body: CoachIn, request: Request) -> dict[str, Any]:
    state = request.app.state.zirak
    symbol = body.symbol
    if body.source == "bot":
        bot = state.runner.bot
        if bot is None:
            raise HTTPException(404, "هنوز رباتی اجرا نشده است")
        symbol = bot.symbol
        trades = trades_from_log([e.to_dict() for e in bot.log])
    elif body.source == "backtest":
        path = state.reports_dir / f"{body.report_id}.json"
        if not body.report_id or not body.report_id.isalnum() or not path.exists():
            raise HTTPException(404, "گزارش بک‌تست پیدا نشد")
        report = json.loads(path.read_text(encoding="utf-8"))
        symbol = report["symbol"]
        trades = trades_from_log(report["trades"])
    elif body.source == "emotional":
        trades = await _emotional_trades(state, symbol)
    else:
        trades = [
            TradeIn(ensure_utc(t.ts), t.side, float(t.price), float(t.qty), float(t.fee_quote))
            for t in body.trades
        ]
    if not trades:
        raise HTTPException(422, "معامله‌ای برای بررسی نیست")
    candles = await state.candles(symbol, "1h", 3000)
    return {"source": body.source, "symbol": symbol, **(await coach(trades, candles, state.llm))}


async def _emotional_trades(state: Any, symbol: str) -> list[TradeIn]:
    """Backtest the built-in emotional (FOMO / panic) trader and return its fills: a demo input."""
    from zirak.backtest.engine import BacktestSetup, run_backtest_async
    from zirak.engine.risk import RiskConfig
    from zirak.fees import FeeModel
    from zirak.strategy.registry import build_strategy

    s = state.settings
    market = await state.market(symbol)
    if market is None:
        raise HTTPException(404, "بازار پیدا نشد")
    candles = await state.candles(symbol, "1h", 2200)
    setup = BacktestSetup(
        market,
        "1h",
        build_strategy("fomo", {}),
        RiskConfig(stop_loss_pct=None, daily_loss_limit_pct=None, max_position_pct=Decimal(100)),
        FeeModel(s.fee_maker, s.fee_taker),
        s.slippage_bps,
        {"TMN": s.paper_start_tmn, "USDT": s.paper_start_usdt}.get(market.quote, Decimal(1000)),
        s.fill_participation,
    )
    report = await run_backtest_async(candles[100:], setup, warmup=candles[:100])
    return trades_from_log(report["trades"])
