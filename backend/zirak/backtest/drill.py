"""Crash drill («مانور سقوط»): a fire drill for your strategy.

The time machine replays a crash that already happened. The drill asks "what if it happens tomorrow?":
it takes the latest *real* candles of a market and continues them with a synthetic stress scenario
(flash crash, slow bleed, pump-and-dump, overnight gap). Then the same strategy runs through the normal
backtester twice, with and without Zirak's risk manager, next to an emotional trader and a plain holder.
The result is a candle-by-candle playback with a Persian narration of every decision.

Scenario prices are clearly synthetic (deterministic, seeded) and start from the real last close. Fills,
fees and slippage follow the usual honest model, so a gap really does sell below the stop price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Any

import numpy as np

from zirak.i18n import fa_pct
from zirak.models import Candle, Market, resolution_delta


@dataclass(frozen=True)
class Scenario:
    key: str
    title_fa: str
    story_fa: str
    #: (number of candles, total % move over them); legs run one after another
    legs: tuple[tuple[int, float], ...]
    #: index of the leg that opens with a gap (the whole move happens between two candles)
    gap_leg: int | None = None


SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        Scenario(
            "flash_crash",
            "سقوط ناگهانی",
            "قیمت در ۶ ساعت ۲۵٪ سقوط می‌کند، بعد کمی برمی‌گردد.",
            ((12, 0.5), (6, -25.0), (24, 12.0), (30, 0.0)),
        ),
        Scenario(
            "slow_bleed",
            "ریزش آرام و طولانی",
            "قیمت هفته‌ها پله‌پله پایین می‌رود و هر برگشت کوچک امید کاذب می‌دهد.",
            ((8, 0.0), (60, -15.0), (20, 5.0), (60, -18.0), (20, 4.0), (40, -12.0)),
        ),
        Scenario(
            "pump_dump",
            "پامپ و دامپ",
            "قیمت یک روزه ۲۵٪ بالا می‌رود و همه هیجان‌زده می‌خرند؛ بعد در چند ساعت ۳۵٪ می‌ریزد.",
            ((8, 0.0), (24, 25.0), (10, -35.0), (40, 2.0)),
        ),
        Scenario(
            "gap_down",
            "شکاف قیمتی شبانه",
            "یک خبر بد شبانه: کندل بعدی ۱۸٪ پایین‌تر باز می‌شود و حد ضرر نمی‌تواند سر جایش اجرا شود.",
            ((24, 3.0), (1, -18.0), (24, -5.0), (30, 1.0)),
            gap_leg=1,
        ),
    )
}

PREFIX_CANDLES = 48  # real candles traded before the scenario starts (so strategies can be in position)


def build_path(history: list[Candle], scenario: Scenario, market: Market, resolution: str) -> list[Candle]:
    """Synthetic candles continuing `history` (its last close) along the scenario's legs."""
    rng = np.random.default_rng(7)  # deterministic: the same drill always plays the same way
    step = resolution_delta(resolution)
    vols = [c.volume for c in history[-200:] if c.volume > 0]
    volume = median(vols) if vols else Decimal(1000)
    price = float(history[-1].close)
    ts: datetime = history[-1].ts
    out: list[Candle] = []
    for i, (n, pct) in enumerate(scenario.legs):
        per = (1 + pct / 100) ** (1 / n) - 1
        for _ in range(n):
            ts = ts + step
            if i == scenario.gap_leg:
                # The whole move happens overnight: the candle opens already gapped.
                close = price * (1 + per)
                open_, hi_lo_from = close, close
            else:
                close = price * (1 + per) * (1 + float(rng.normal(0, 0.003)))
                open_, hi_lo_from = price, price
            hi = max(open_, close, hi_lo_from) * (1 + abs(float(rng.normal(0, 0.002))))
            lo = min(open_, close, hi_lo_from) * (1 - abs(float(rng.normal(0, 0.002))))
            out.append(
                Candle(
                    ts,
                    market.round_price(Decimal(str(open_))),
                    market.round_price(Decimal(str(hi))),
                    market.round_price(Decimal(str(lo))),
                    market.round_price(Decimal(str(close))),
                    volume,
                )
            )
            price = close
    return out


def outcome(pct: float) -> str:
    """ "۱٫۲٪ سود" / "۰٫۴٪ زیان": no minus signs inside Persian sentences."""
    if abs(pct) < 0.05:
        return "تقریباً بدون تغییر"
    return f"{fa_pct(abs(pct))} {'سود' if pct > 0 else 'زیان'}"


def _curve_index(report: dict[str, Any]) -> dict[str, int]:
    return {p["ts"]: i for i, p in enumerate(report["equity_curve"])}


def narrate(report: dict[str, Any], scenario_start: int, sl_pct: float | None) -> list[dict[str, Any]]:
    """Persian timeline of what the protected bot did, keyed to the playback index."""
    idx = _curve_index(report)
    events: list[dict[str, Any]] = []
    last_block = ""
    for t in report["trades"]:
        i = idx.get(t["ts"])
        if i is None:
            continue
        approved = t["decision"]["approved"]
        if not approved:
            code = t["decision"]["code"]
            if t["side"] == "buy" and code != last_block:
                notes = t["decision"].get("notes_fa") or []
                why = notes[0] if notes else "ریسک این خرید بیش از حد مجاز بود."
                events.append({"i": i, "kind": "blocked", "text_fa": f"🛡️ زیرک خرید را رد کرد: {why}"})
            last_block = code
            continue
        last_block = ""
        if float(t.get("filled_qty") or 0) <= 0:
            continue
        reason, note = t["reason"], t["note_fa"]
        if t["side"] == "buy":
            events.append({"i": i, "kind": "buy", "text_fa": f"🟢 خرید: {note}"})
        elif reason == "stop_loss":
            text = f"🛑 حد ضرر: {note}"
            pnl = float(t["pnl_pct"]) if t.get("pnl_pct") else None
            if sl_pct is not None and pnl is not None and pnl < -(sl_pct + 1):
                text += (
                    f" به‌خاطر شکاف قیمت، فروش با {fa_pct(-pnl)} زیان انجام شد نه {fa_pct(sl_pct)}؛"
                    " حد ضرر سقف تضمینی نیست، ولی جلوی زیان بیشتر را می‌گیرد."
                )
            events.append({"i": i, "kind": "stop", "text_fa": text})
        elif reason == "daily_loss_limit":
            events.append({"i": i, "kind": "halt", "text_fa": f"⛔ سقف زیان روزانه: {note}"})
        elif reason == "take_profit":
            events.append({"i": i, "kind": "profit", "text_fa": f"💰 حد سود: {note}"})
        else:
            events.append({"i": i, "kind": "sell", "text_fa": f"🔴 فروش: {note}"})
    events.append(
        {"i": scenario_start, "kind": "start", "text_fa": "🔥 مانور شروع شد؛ از این لحظه قیمت‌ها ساختگی‌اند."}
    )
    events.sort(key=lambda e: (e["i"], e["kind"] != "start"))
    return events


def _normalised(values: list[float], at: int = 0) -> list[float]:
    """100 = the value at index `at` (the moment the drill starts)."""
    base = values[at] if at < len(values) and values[at] else 1.0
    return [round(v / base * 100, 3) for v in values]


def _max_dd(values: list[float]) -> float:
    peak, worst = values[0] if values else 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1 if peak else 0.0)
    return round(worst * 100, 2)


def assemble(
    scenario: Scenario,
    quote: str,
    scenario_start_ts: datetime,
    protected: dict[str, Any],
    naked: dict[str, Any],
    emotional: dict[str, Any],
    sl_pct: float | None,
) -> dict[str, Any]:
    curve = protected["equity_curve"]
    x = [p["ts"] for p in curve]
    start_i = next((i for i, p in enumerate(curve) if p["ts"] > scenario_start_ts.isoformat()), 0)
    prices = [p["price"] for p in curve]
    lines = {
        "zirak": [p["equity"] for p in curve],
        "naked": [p["equity"] for p in naked["equity_curve"]],
        "emotional": [p["equity"] for p in emotional["equity_curve"]],
        "hold": [p["buy_hold"] for p in curve],
    }
    titles = {
        "zirak": "استراتژی شما + زیرک",
        "naked": "همان استراتژی بدون سپر",
        "emotional": "معامله‌گر هیجانی",
        "hold": "خرید و نگهداری",
    }
    results: list[dict[str, Any]] = []
    for key, vals in lines.items():
        # Measured over the drill itself (from the moment the scenario starts).
        part = vals[start_i:] if start_i < len(vals) else vals
        results.append(
            {
                "key": key,
                "title_fa": titles[key],
                "return_pct": round((part[-1] / part[0] - 1) * 100, 2) if part and part[0] else 0.0,
                "max_drawdown_pct": _max_dd(part),
            }
        )
    by = {r["key"]: r for r in results}
    path = prices[start_i:]
    bottom = round((min(path) / path[0] - 1) * 100, 2) if path else 0.0
    events = narrate(protected, start_i, sl_pct)
    if path:
        b_i = start_i + path.index(min(path))
        events.append(
            {"i": b_i, "kind": "bottom", "text_fa": f"📉 کف مانور: قیمت {fa_pct(-bottom)} پایین‌تر از شروع."}
        )
        events.sort(key=lambda e: e["i"])
    z, n, e, h = by["zirak"], by["naked"], by["emotional"], by["hold"]
    headline = (
        f"در مانور «{scenario.title_fa}» قیمت تا {fa_pct(-bottom)} ریخت. "
        f"با زیرک: {outcome(z['return_pct'])} (بیشترین افت {fa_pct(-z['max_drawdown_pct'])})؛ "
        f"همان استراتژی بدون سپر: {outcome(n['return_pct'])}؛ معامله‌گر هیجانی: {outcome(e['return_pct'])}؛ "
        f"خرید و نگهداری: {outcome(h['return_pct'])}."
    )
    blocked = sum(1 for t in protected["trades"] if not t["decision"]["approved"] and t["ts"] >= x[start_i])
    return {
        "scenario": {"key": scenario.key, "title_fa": scenario.title_fa, "story_fa": scenario.story_fa},
        "quote": quote,
        "start_index": start_i,
        "x": x,
        "price": prices,
        "lines": {k: _normalised(v, start_i) for k, v in lines.items()},
        "titles_fa": titles,
        "results": results,
        "bottom_pct": bottom,
        "blocked": blocked,
        "events": events[:40],
        "markers": [
            {
                "ts": t["ts"],
                "side": t["side"],
                "label": t["note_fa"],
                "blocked": not t["decision"]["approved"],
            }
            for t in protected["trades"]
            if t["ts"] >= x[start_i]
            and (not t["decision"]["approved"] or float(t.get("filled_qty") or 0) > 0)
        ],
        "headline_fa": headline,
        "note_fa": "قیمت‌های بعد از شروع مانور ساختگی و فقط برای آزمون استرس‌اند؛ پیش‌بینی بازار نیستند.",
    }
