"""Hero insights on top of backtests: periods (incl. "the worst crash"), the Zirak Score, and the
risk-shield counterfactual (same strategy without Zirak's risk manager)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from zirak.engine.risk import RiskConfig
from zirak.i18n import fa_num, fa_pct, tehran_time
from zirak.models import RESOLUTION_SECONDS, Candle

PERIOD_DAYS = {"30d": 30, "90d": 90, "180d": 180, "365d": 365}
PERIOD_FA = {
    "30d": "۳۰ روز اخیر",
    "90d": "۹۰ روز اخیر",
    "180d": "۶ ماه اخیر",
    "365d": "یک سال اخیر",
    "all": "کل داده‌ها",
    "crash": "بدترین ریزش",
}
WARMUP_CANDLES = 150


@dataclass
class Period:
    key: str
    title_fa: str
    warmup: list[Candle]  # fed to the strategy as history, never traded
    candles: list[Candle]  # traded and measured
    note_fa: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title_fa": self.title_fa,
            "note_fa": self.note_fa,
            "start": self.candles[0].ts.isoformat(),
            "end": self.candles[-1].ts.isoformat(),
            "candles": len(self.candles),
        }


def worst_drawdown(candles: list[Candle]) -> tuple[int, int, float]:
    """(peak index, trough index, drawdown %) of the deepest peak-to-trough fall in closes."""
    peak_i, best = 0, (0, 0, 0.0)
    peak = float(candles[0].close)
    for i, c in enumerate(candles):
        px = float(c.close)
        if px > peak:
            peak, peak_i = px, i
        dd = (px / peak - 1) * 100
        if dd < best[2]:
            best = (peak_i, i, dd)
    return best


def select_period(series: list[Candle], key: str, resolution: str) -> Period:
    per_day = 86400 // RESOLUTION_SECONDS[resolution]
    if key in PERIOD_DAYS:
        n = max(30, PERIOD_DAYS[key] * per_day)
        start = max(0, len(series) - n)
        note = ""
    elif key == "crash":
        p, t, dd = worst_drawdown(series)
        pad_before, pad_after = 3 * per_day, 10 * per_day
        start = max(0, p - pad_before)
        end = min(len(series), t + pad_after)
        note = (
            f"قیمت از {tehran_time(series[p].ts)} تا {tehran_time(series[t].ts)} حدود "
            f"{fa_pct(-dd)} ریزش کرد؛ ببینیم زیرک در آن روزها چه می‌کرد."
        )
        return Period(
            key, PERIOD_FA[key], series[max(0, start - WARMUP_CANDLES) : start], series[start:end], note
        )
    else:
        start, note = 0, ""
        key = "all"
    return Period(key, PERIOD_FA[key], series[max(0, start - WARMUP_CANDLES) : start], series[start:], note)


# ---- Zirak Score ---------------------------------------------------------------------------------
def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


GRADES = [(80, "A", "عالی"), (65, "B", "خوب"), (50, "C", "متوسط"), (35, "D", "ضعیف"), (0, "E", "پرخطر")]


def zirak_score(m: dict[str, Any]) -> dict[str, Any]:
    """0-100: profit (20), capital protection (30), edge over buy-and-hold (35), consistency (15).
    Edge weighs most, so a strategy that loses little in a crash still scores fairly."""
    ret, dd = float(m["return_pct"]), float(m["max_drawdown_pct"])
    bh, bh_dd = float(m["buy_hold_return_pct"]), float(m["buy_hold_max_drawdown_pct"])
    trades, win = int(m["trades"]), float(m["win_rate_pct"])
    profit = 20 * _clamp(0.5 + ret / 20)
    protection = 30 * _clamp(1 - abs(dd) / 25)
    edge = 35 * _clamp(0.5 + (ret - bh) / 30 + (dd - bh_dd) / 60)
    consistency = 15 * (_clamp(win / 70) if trades >= 3 else 0.3)
    score = round(profit + protection + edge + consistency)
    grade, grade_fa = next((g, fa) for floor, g, fa in GRADES if score >= floor)
    parts = []
    parts.append(f"بازده {fa_pct(ret, 1)} در برابر {fa_pct(bh, 1)} برای خرید و نگهداری")
    parts.append(f"بیشترین افت سرمایه {fa_pct(abs(dd), 1)} (نگهداری: {fa_pct(abs(bh_dd), 1)})")
    if trades:
        parts.append(f"{fa_num(trades, 0)} معامله با {fa_pct(win, 0)} برد")
    else:
        parts.append("در این دوره هیچ معامله‌ای بسته نشد")
    if abs(dd) < abs(bh_dd) * 0.6:
        headline = "ریسک را خیلی کمتر از نگهداری نگه داشت."
    elif ret > bh and dd >= bh_dd:
        headline = "هم سود بیشتر، هم ریسک کمتر از نگهداری."
    elif ret > bh:
        headline = "از نگهداری سود بیشتری داشت، ولی با نوسان بیشتر."
    else:
        headline = "از نگهداری عقب ماند؛ قبل از اجرا پارامترها را بازبینی کنید."
    return {
        "score": score,
        "grade": grade,
        "grade_fa": grade_fa,
        "headline_fa": headline,
        "details_fa": "؛ ".join(parts) + ".",
        "components": {
            "profit": round(profit, 1),
            "protection": round(protection, 1),
            "edge": round(edge, 1),
            "consistency": round(consistency, 1),
        },
    }


# ---- Risk shield ------------------------------------------------------------------------------------
def unprotected(risk: RiskConfig) -> RiskConfig:
    """The same strategy with Zirak's safety net removed (keeps the strategy's own take-profit)."""
    return RiskConfig(
        max_position_pct=Decimal("100"),
        max_order_quote=None,
        stop_loss_pct=None,
        take_profit_pct=risk.take_profit_pct,
        daily_loss_limit_pct=None,
        cooldown_candles=0,
        flatten_on_halt=False,
    )


RISK_REASONS = {"stop_loss", "daily_loss_limit"}


def risk_shield(protected: dict[str, Any], naked: dict[str, Any], quote: str) -> dict[str, Any]:
    pm, nm = protected["metrics"], naked["metrics"]
    saved_quote = float(pm["end_equity"]) - float(nm["end_equity"])
    dd_cut = abs(float(nm["max_drawdown_pct"])) - abs(float(pm["max_drawdown_pct"]))
    blocked = sum(1 for t in protected["trades"] if not t["decision"]["approved"])
    exits = sum(1 for t in protected["trades"] if t["reason"] in RISK_REASONS and t["decision"]["approved"])
    unit = "تومان" if quote == "TMN" else "تتر"
    dec = 0 if quote == "TMN" else 2
    if saved_quote > 0 and dd_cut > 0:
        msg = (
            f"سپر ریسک زیرک {fa_num(saved_quote, dec)} {unit} از سرمایه را حفظ کرد و بیشترین افت را "
            f"{fa_pct(dd_cut, 1)} کمتر کرد."
        )
    elif dd_cut > 0:
        msg = (
            f"سپر ریسک {fa_num(-saved_quote, dec)} {unit} از سود را گرفت، ولی در عوض بیشترین افت "
            f"سرمایه را {fa_pct(dd_cut, 1)} کمتر کرد؛ یعنی شب‌ها راحت‌تر بخوابید."
        )
    elif saved_quote > 0:
        msg = f"سپر ریسک {fa_num(saved_quote, dec)} {unit} نتیجه را بهتر کرد."
    elif saved_quote < 0:
        msg = (
            f"صادقانه: در این دوره حد ضرر چند بار زودتر از بازار خارج شد و بدون سپر نتیجه "
            f"{fa_num(-saved_quote, dec)} {unit} بهتر بود. سپر برای روزهای بد است، نه برای همهٔ روزها."
        )
    else:
        msg = "در این دوره سپر ریسک لازم نشد؛ بازار آرام بود یا استراتژی خودش محتاط است."
    return {
        "saved_quote": round(saved_quote, 2),
        "drawdown_cut_pct": round(dd_cut, 2),
        "blocked_orders": blocked,
        "risk_exits": exits,
        "message_fa": msg,
        "with_shield": {k: pm[k] for k in ("return_pct", "max_drawdown_pct", "end_equity")},
        "without_shield": {k: nm[k] for k in ("return_pct", "max_drawdown_pct", "end_equity")},
        "without_curve": [{"ts": p["ts"], "equity": p["equity"]} for p in naked["equity_curve"]],
    }
