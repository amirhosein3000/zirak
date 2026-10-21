""" "Why did the bot do that?" — explanations built from the logged signal, indicators and risk decision."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from zirak.i18n import fa_num, fa_pct, tehran_time
from zirak.llm.provider import LLMProvider
from zirak.models import ensure_utc

REJECT_FA = {
    "killed": "کلید توقف اضطراری فعال بود",
    "daily_loss_limit": "به سقف زیان روزانه رسیده بودیم",
    "halted": "معاملات متوقف بود",
    "cooldown": "دورهٔ استراحت بعد از فروش تمام نشده بود",
    "max_exposure": "سهم این دارایی از سرمایه به سقف رسیده بود",
    "below_min_notional": "مبلغ سفارش کمتر از حداقل بازار بود",
    "below_min_qty": "مقدار سفارش کمتر از حداقل بازار بود",
    "no_position": "موقعیتی برای فروش نبود",
    "no_equity": "سرمایه‌ای نبود",
}

INDICATOR_FA = {
    "close": "قیمت بسته‌شدن",
    "change_from_high_pct": "فاصله از سقف اخیر (٪)",
    "change_from_low_pct": "فاصله از کف اخیر (٪)",
    "change_from_entry_pct": "تغییر نسبت به میانگین خرید (٪)",
    "avg_entry": "میانگین قیمت خرید",
    "daily_loss_pct": "زیان امروز (٪)",
    "gain_pct": "سود سبد (٪)",
}


def template_explanation(entry: dict[str, Any]) -> str:
    from datetime import datetime

    ts = tehran_time(ensure_utc(datetime.fromisoformat(entry["ts"])))
    action = "خرید" if entry["side"] == "buy" else "فروش"
    decision = entry["decision"]
    lines = [f"در {ts} (به وقت تهران) ربات تصمیم به {action} گرفت. دلیل: {entry['note_fa']}"]
    ind = entry.get("indicators") or {}
    if ind:
        shown = [f"{INDICATOR_FA.get(k, k)} = {fa_num(v, 2)}" for k, v in list(ind.items())[:5]]
        lines.append("داده‌هایی که دید: " + "، ".join(shown) + ".")
    if not decision["approved"]:
        why = REJECT_FA.get(decision["code"], decision["code"])
        lines.append(f"اما مدیر ریسک اجازه نداد، چون {why}. هیچ سفارشی ثبت نشد.")
    else:
        lines.append(f"مدیر ریسک مقدار {fa_num(Decimal(decision['qty']), 6)} را تأیید کرد.")
        lines.extend(decision.get("notes_fa") or [])
        if entry.get("avg_price"):
            fee = Decimal(entry.get("fee") or "0")
            lines.append(
                f"سفارش با میانگین قیمت {fa_num(Decimal(entry['avg_price']), 2)} اجرا شد"
                + (f" و کارمزد {fa_num(fee, 6)} {entry.get('fee_asset', '')} پرداخت شد." if fee else ".")
            )
        if entry.get("pnl") is not None:
            pnl = Decimal(entry["pnl"])
            word = "سود" if pnl >= 0 else "زیان"
            pct = f" ({fa_pct(Decimal(entry['pnl_pct']))})" if entry.get("pnl_pct") else ""
            lines.append(f"نتیجهٔ این فروش: {word} {fa_num(abs(pnl), 2)}{pct} پس از کسر کارمزد.")
    return " ".join(lines)


SYSTEM_PROMPT = (
    "You explain one automated trading decision to a retail user in simple Persian (3-5 sentences). "
    "Use ONLY the JSON facts: the signal reason, indicator values, the risk manager decision and the fill. "
    "Use Persian digits. Do not invent anything or give advice."
)


async def explain_entry(llm: LLMProvider, entry: dict[str, Any]) -> tuple[str, str]:
    text = await llm.chat(SYSTEM_PROMPT, json.dumps(entry, ensure_ascii=False))
    if text and text.strip():
        return text.strip(), llm.name
    return template_explanation(entry), "template"
