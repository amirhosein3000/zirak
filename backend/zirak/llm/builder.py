"""Natural-language (Persian) strategy builder.

Text -> StrategySpec JSON (validated with pydantic) -> plain-Persian description for the user to confirm.
With a real LLM, the model writes the JSON; if it fails validation we fall back to the rule-based
parser below. With MOCK_LLM=true only the rule-based parser runs. Nothing here can place an order.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from zirak.i18n import en_digits, fa_pct
from zirak.llm.provider import LLMProvider
from zirak.strategy.spec import StrategySpec

DEFAULT_STOP_LOSS = 5.0
DEFAULT_SIZE = 10.0

ASSETS = [
    (r"بیت\s*‌?\s*کوین|بیتکوین|btc|bitcoin", "BTC"),
    (r"اتریوم|اتر(?!\w)|eth|ethereum", "ETH"),
    (r"تتر|usdt|دلار", "USDT"),
]

NUM = r"(\d+(?:\.\d+)?)"
PCT = NUM + r"\s*(?:٪|%|درصد)"


@dataclass
class BuildResult:
    spec: StrategySpec | None
    description_fa: list[str] = field(default_factory=list)
    warnings_fa: list[str] = field(default_factory=list)
    source: str = "rules"
    error_fa: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.model_dump() if self.spec else None,
            "description_fa": self.description_fa,
            "warnings_fa": self.warnings_fa,
            "source": self.source,
            "error_fa": self.error_fa,
        }


def normalize(text: str) -> str:
    t = en_digits(text).lower()
    t = t.replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", t)


def _symbol(t: str, default_symbol: str | None) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    base = None
    for pattern, asset in ASSETS:
        if re.search(pattern, t) and asset != "USDT":
            base = asset
            break
    quote = "USDT" if re.search(r"تتری|به تتر|با تتر|usdt", t) and base else "TMN"
    if base is None:
        if re.search(ASSETS[2][0], t):
            return "USDTTMN", warnings
        if default_symbol:
            return default_symbol, ["ارز در متن مشخص نبود؛ بازار انتخاب‌شده استفاده شد."]
        return None, warnings
    return f"{base}{quote}", warnings


def _resolution(t: str) -> str:
    if re.search(r"روزانه|روزی|هر روز", t):
        return "1d"
    if re.search(r"۴\s*ساعت|4\s*ساعت|چهار\s*ساعت", t):
        return "4h"
    if re.search(r"۱۵\s*دقیقه|15\s*دقیقه|ربع", t):
        return "15m"
    return "1h"


def _lookback_hours(t: str) -> int | None:
    unit = r"\s*(ساعت|روز|هفته)(?!ه)"  # "۴ ساعته" names the chart, not a lookback
    m = re.search(r"(?:در|طی|ظرف)\s*" + NUM + unit, t) or re.search(NUM + unit, t)
    if m:
        n = float(m.group(1))
        return int(n * {"ساعت": 1, "روز": 24, "هفته": 168}[m.group(2)])
    if re.search(r"یک روز|یه روز|امروز", t):
        return 24
    if re.search(r"یک هفته|یه هفته", t):
        return 168
    return None


# What a percentage means, judged by the keyword right before it ("حد ضرر ۴٪") or the nearest one after it.
PCT_BEFORE = [("tp", r"(حد\s*سود|تارگت|هدف)\s*:?\s*$"), ("sl", r"(حد\s*ضرر|حد\s*زیان|استاپ)\s*:?\s*$")]
PCT_AFTER = [
    ("tp", r"سود"),
    ("sl", r"ضرر|زیان|استاپ"),
    ("size", r"سرمایه|موجودی|پول|دارایی|بودجه"),
    ("drop", r"ریخت|بریزه|بریزد|افت|کاهش|ریزش|پایین|کم شد|سقوط|دامپ"),
    ("rise", r"رشد|افزایش|بالا|پامپ|جهش"),
]


def _classify_pct(before: str, after: str) -> str | None:
    for kind, pattern in PCT_BEFORE:
        if re.search(pattern, before):
            return kind
    best: tuple[int, str] | None = None
    for kind, pattern in PCT_AFTER:
        m = re.search(pattern, after)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), kind)
    return best[1] if best else None


def parse_rules(text: str, default_symbol: str | None = None) -> BuildResult:
    """Rule-based Persian parser for common phrasings. Deterministic; used offline and as LLM fallback."""
    t = normalize(text)
    symbol, warnings = _symbol(t, default_symbol)
    if symbol is None:
        return BuildResult(None, error_fa="ارز مورد نظر را پیدا نکردم. مثلاً بنویسید «بیت‌کوین» یا «اتریوم».")
    resolution = _resolution(t)
    entry: list[dict[str, Any]] = []
    size = tp = sl = None
    for m in re.finditer(PCT, t):
        value = float(m.group(1))
        kind = _classify_pct(t[max(0, m.start() - 25) : m.start()], t[m.end() : m.end() + 30])
        if kind == "tp":
            tp = value
        elif kind == "sl":
            sl = value
        elif kind == "size":
            size = value
        elif kind == "drop":
            entry.append({"kind": "drop_from_high", "pct": value})
        elif kind == "rise":
            entry.append({"kind": "rise_from_low", "pct": value})
    m_rsi = re.search(r"(rsi|آر\s*اس\s*آی)[^\d]{0,20}" + r"(زیر|کمتر از|پایین‌تر از|پایین تر از)\s*" + NUM, t)
    if m_rsi:
        entry.append({"kind": "rsi_below", "value": float(m_rsi.group(3))})
    if re.search(r"تقاطع|کراس|میانگین متحرک", t) and re.search(r"بالا|صعود", t):
        entry.append({"kind": "ema_cross_up"})
    if not entry:
        return BuildResult(
            None,
            warnings_fa=warnings,
            error_fa="شرط خرید را متوجه نشدم. مثال: «وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش».",
        )
    lookback = _lookback_hours(t)
    candle_hours = {"15m": 0.25, "1h": 1, "4h": 4, "1d": 24}[resolution]
    for cond in entry:
        if cond["kind"] in ("drop_from_high", "rise_from_low"):
            cond["lookback"] = max(2, int((lookback or 24) / candle_hours))
            if lookback is None:
                warnings.append("بازهٔ زمانی ریزش/رشد مشخص نبود؛ ۲۴ ساعت گذشته در نظر گرفته شد.")
    if size is None:
        size = DEFAULT_SIZE
        warnings.append(f"درصد سرمایه مشخص نبود؛ {fa_pct(DEFAULT_SIZE, 0)} در نظر گرفته شد.")
    if sl is None:
        sl = DEFAULT_STOP_LOSS
        warnings.append(
            f"حد ضرر نگفته بودید؛ برای امنیت حد ضرر {fa_pct(DEFAULT_STOP_LOSS, 0)} اضافه شد (قابل تغییر)."
        )
    raw = {
        "name": text.strip()[:60] or "استراتژی من",
        "symbol": symbol,
        "resolution": resolution,
        "entry": entry,
        "position_size_pct": size,
        "take_profit_pct": tp,
        "stop_loss_pct": sl,
        "cooldown_candles": 3,
    }
    try:
        spec = StrategySpec.model_validate(raw)
    except ValidationError as e:
        return BuildResult(None, warnings_fa=warnings, error_fa=f"قوانین معتبر نبود: {e.errors()[0]['msg']}")
    return BuildResult(spec, spec.describe_fa(), warnings, "rules")


SYSTEM_PROMPT = """You convert a Persian trading idea into JSON for a deterministic trading engine.
Output ONLY a JSON object matching this schema (no prose):
{
 "name": str, "symbol": one of ["USDTTMN","BTCTMN","BTCUSDT","ETHTMN","ETHUSDT"],
 "resolution": one of ["15m","1h","4h","1d"],
 "entry": [condition, ...]   // ALL must hold to buy
 "exit": [condition, ...]    // ANY triggers a full sell (optional)
 "position_size_pct": number (0-100], "take_profit_pct": number|null, "stop_loss_pct": number|null,
 "max_entries": int>=1, "cooldown_candles": int>=0
}
condition = {"kind": "drop_from_high"|"rise_from_low", "pct": number, "lookback": candles}
          | {"kind": "rsi_below"|"rsi_above", "value": 0-100, "period": int}
          | {"kind": "ema_cross_up"|"ema_cross_down", "fast": int, "slow": int}
          | {"kind": "price_below"|"price_above", "value": number}
Rules: Toman markets end in TMN. "ریخت" (dropped) means drop_from_high; lookback counts candles of the
chosen resolution (24h on 1h candles = 24). If the user gives no stop-loss, set stop_loss_pct to 5.
Never invent conditions the user did not ask for."""


async def build_strategy(llm: LLMProvider, text: str, default_symbol: str | None = None) -> BuildResult:
    raw = await llm.chat(SYSTEM_PROMPT, f"default market: {default_symbol}\nidea: {text}", json_mode=True)
    if raw:
        try:
            data = json.loads(raw)
            spec = StrategySpec.model_validate(data)
            warnings = []
            if spec.stop_loss_pct is None:
                spec.stop_loss_pct = DEFAULT_STOP_LOSS
                warnings.append(f"برای امنیت حد ضرر {fa_pct(DEFAULT_STOP_LOSS, 0)} اضافه شد (قابل تغییر).")
            return BuildResult(spec, spec.describe_fa(), warnings, llm.name)
        except (json.JSONDecodeError, ValidationError, TypeError):
            pass  # fall back to deterministic rules
    result = parse_rules(text, default_symbol)
    if raw:
        result.warnings_fa.insert(0, "پاسخ هوش مصنوعی معتبر نبود؛ از تحلیل‌گر قانون‌محور استفاده شد.")
    return result
