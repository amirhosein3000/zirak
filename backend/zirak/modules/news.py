"""Persian news & sentiment.

Sources: `mock` (canned, offline, clearly labelled as sample headlines) or `rss` (official RSS / Atom
feeds listed in NEWS_RSS_URLS; no scraping). Sentiment is a transparent keyword score in [-1, 1]; the
LLM (when configured) only writes the Persian summary, with a deterministic template as fallback.

Optional risk input (NEWS_RISK=true): very negative news shrinks new buys of the running bot via
`RiskManager.size_factor` (0.5 or 0.75). It can never enlarge a trade.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from fastapi import APIRouter, Request

from zirak.config import Settings
from zirak.i18n import fa_num
from zirak.llm.provider import LLMProvider
from zirak.markets import ASSET_NAMES_FA
from zirak.models import ensure_utc, utcnow

POSITIVE = {
    "surge",
    "surges",
    "rally",
    "rallies",
    "gain",
    "gains",
    "jump",
    "jumps",
    "soar",
    "soars",
    "record",
    "approval",
    "approved",
    "adopt",
    "adoption",
    "inflow",
    "inflows",
    "bullish",
    "rebound",
    "upgrade",
    "partnership",
    "launch",
    "high",
    "rise",
    "rises",
    "recovery",
    "رشد",
    "صعود",
    "افزایش",
    "رکورد",
    "تایید",
    "تأیید",
    "ورود سرمایه",
    "بازگشت",
    "خوش‌بینی",
}
NEGATIVE = {
    "crash",
    "crashes",
    "plunge",
    "plunges",
    "drop",
    "drops",
    "fall",
    "falls",
    "hack",
    "hacked",
    "exploit",
    "ban",
    "bans",
    "lawsuit",
    "sues",
    "fraud",
    "outflow",
    "outflows",
    "bearish",
    "selloff",
    "sell-off",
    "liquidation",
    "liquidations",
    "bankruptcy",
    "collapse",
    "fear",
    "warning",
    "probe",
    "low",
    "slump",
    "سقوط",
    "ریزش",
    "کاهش",
    "هک",
    "ممنوع",
    "شکایت",
    "کلاهبرداری",
    "خروج سرمایه",
    "ترس",
    "هشدار",
    "ورشکستگی",
}
ASSET_WORDS = {
    "BTC": ("bitcoin", "btc", "بیت‌کوین", "بیت کوین"),
    "ETH": ("ethereum", "eth", "ether", "اتریوم"),
    "USDT": ("tether", "usdt", "stablecoin", "تتر"),
}

MOCK_HEADLINES: list[tuple[str, str]] = [
    ("Bitcoin ETF inflows rise for a third straight week", "sample"),
    ("Ethereum developers launch upgrade on testnet", "sample"),
    ("Crypto exchange hacked, $40M drained from hot wallet", "sample"),
    ("Regulators warn retail investors about leverage in crypto", "sample"),
    ("Bitcoin rebounds after weekend sell-off", "sample"),
    ("Tether reports record reserves in quarterly attestation", "sample"),
    ("بازار رمزارزها پس از ریزش دیروز به آرامی بازگشت", "sample"),
    ("هشدار دربارهٔ کلاهبرداری با وعدهٔ سود تضمینی در رمزارزها", "sample"),
]


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    url: str | None
    published: str | None  # ISO UTC
    score: float  # -1 .. 1
    assets: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _words(text: str) -> list[str]:
    return re.findall(r"[\w؀-ۿ‌-]+", text.lower())


def score_text(text: str) -> float:
    words = _words(text)
    joined = " ".join(words)
    pos = sum(1 for w in words if w in POSITIVE) + sum(1 for p in POSITIVE if " " in p and p in joined)
    neg = sum(1 for w in words if w in NEGATIVE) + sum(1 for n in NEGATIVE if " " in n and n in joined)
    return 0.0 if pos + neg == 0 else (pos - neg) / (pos + neg)


def assets_in(text: str) -> list[str]:
    low = text.lower()
    return [a for a, words in ASSET_WORDS.items() if any(w in low for w in words)]


def make_item(title: str, source: str, url: str | None = None, published: datetime | None = None) -> NewsItem:
    return NewsItem(
        title.strip(),
        source,
        url,
        ensure_utc(published).isoformat() if published else None,
        round(score_text(title), 3),
        assets_in(title),
    )


def parse_feed(xml_text: str, source: str) -> list[NewsItem]:
    """RSS 2.0 (`channel/item`) or Atom (`entry`). Unknown shapes give an empty list."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[NewsItem] = []
    for it in root.iter():
        tag = it.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = date = None
        for ch in it:
            name = ch.tag.rsplit("}", 1)[-1]
            if name == "title":
                title = (ch.text or "").strip()
            elif name == "link":
                link = (ch.text or ch.attrib.get("href") or "").strip() or None
            elif name in ("pubDate", "published", "updated") and date is None:
                date = (ch.text or "").strip()
        if not title:
            continue
        published: datetime | None = None
        if date:
            try:
                published = parsedate_to_datetime(date)
            except (TypeError, ValueError):
                try:
                    published = datetime.fromisoformat(date.replace("Z", "+00:00"))
                except ValueError:
                    published = None
        items.append(make_item(title, source, link, published))
    return items


async def fetch_news(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> list[NewsItem]:
    if settings.news_source != "rss" or not settings.news_rss_urls:
        now = utcnow()
        return [make_item(t, s, None, now) for t, s in MOCK_HEADLINES]
    out: list[NewsItem] = []
    async with httpx.AsyncClient(timeout=10, transport=transport, follow_redirects=True) as client:
        for url in settings.news_rss_urls:
            try:
                r = await client.get(url, headers={"User-Agent": "Zirak/0.1 (RSS reader)"})
                r.raise_for_status()
            except httpx.HTTPError:
                continue
            host = httpx.URL(url).host
            out.extend(parse_feed(r.text, host)[:20])
    out.sort(key=lambda n: n.published or "", reverse=True)
    return out[:40]


@dataclass(frozen=True)
class Sentiment:
    score: float  # mean of item scores, -1 .. 1
    label_fa: str
    positive: int
    negative: int
    neutral: int
    size_factor: float  # what NEWS_RISK would apply to new buys
    summary_fa: str
    items: list[NewsItem]
    source: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["items"] = [i.to_dict() for i in self.items]
        return d


def size_factor_for(score: float) -> float:
    if score <= -0.4:
        return 0.5
    if score <= -0.2:
        return 0.75
    return 1.0


def label_for(score: float) -> str:
    if score >= 0.25:
        return "مثبت"
    if score <= -0.25:
        return "منفی"
    return "خنثی"


def template_summary(items: list[NewsItem], score: float, asset: str | None) -> str:
    pos = sum(1 for i in items if i.score > 0)
    neg = sum(1 for i in items if i.score < 0)
    about = f" دربارهٔ {ASSET_NAMES_FA.get(asset, asset)}" if asset else ""
    text = (
        f"از {fa_num(len(items), 0)} خبر اخیر{about}، {fa_num(pos, 0)} خبر لحن مثبت و "
        f"{fa_num(neg, 0)} خبر لحن منفی دارند؛ حال‌وهوای کلی خبرها «{label_for(score)}» است."
    )
    worst = min(items, key=lambda i: i.score, default=None)
    if worst is not None and worst.score < 0:
        text += f" منفی‌ترین تیتر: «{worst.title}»."
    return text + " این تحلیل خودکار و ساده است و توصیهٔ مالی نیست."


async def analyse(items: list[NewsItem], llm: LLMProvider, asset: str | None, source: str) -> Sentiment:
    if asset:
        items = [i for i in items if asset in i.assets] or items
    score = sum(i.score for i in items) / len(items) if items else 0.0
    summary = template_summary(items, score, asset) if items else "خبری پیدا نشد."
    if items:
        heads = "\n".join(f"- {i.title} (score {i.score:+.2f})" for i in items[:15])
        llm_text = await llm.chat(
            "You summarise crypto news for Iranian retail traders. Write 2-3 short sentences in Persian, "
            "neutral and factual, no advice, no predictions. Mention the overall tone.",
            heads,
        )
        if llm_text:
            summary = llm_text.strip() + " (این خلاصه توصیهٔ مالی نیست.)"
    return Sentiment(
        round(score, 3),
        label_for(score),
        sum(1 for i in items if i.score > 0),
        sum(1 for i in items if i.score < 0),
        sum(1 for i in items if i.score == 0),
        size_factor_for(score),
        summary,
        items,
        source,
    )


# ---- API ---------------------------------------------------------------------------------------
router = APIRouter()
_cache: dict[str, tuple[float, list[NewsItem]]] = {}


async def _items(settings: Settings) -> list[NewsItem]:
    hit = _cache.get(settings.news_source)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    items = await fetch_news(settings)
    _cache[settings.news_source] = (time.monotonic(), items)
    return items


@router.get("")
async def news(request: Request, asset: str | None = None) -> dict[str, Any]:
    state = request.app.state.zirak
    s: Settings = state.settings
    result = await analyse(await _items(s), state.llm, asset, s.news_source)
    return {**result.to_dict(), "news_risk_enabled": s.news_risk}


@router.post("/apply")
async def apply(request: Request, asset: str | None = None) -> dict[str, Any]:
    """NEWS_RISK=true: set the running bot's buy-size factor from current news (never above 1)."""
    state = request.app.state.zirak
    s: Settings = state.settings
    if not s.news_risk:
        return {"applied": False, "reason": "NEWS_RISK is off"}
    bot = state.runner.bot
    if bot is None:
        return {"applied": False, "reason": "no bot"}
    result = await analyse(await _items(s), state.llm, asset, s.news_source)
    bot.risk.size_factor = Decimal(str(result.size_factor))
    bot.risk.size_factor_note_fa = (
        f"به‌خاطر خبرهای منفی (امتیاز {fa_num(result.score, 2)}) حجم خرید کم شد."
        if result.size_factor < 1
        else ""
    )
    return {"applied": True, "size_factor": result.size_factor, "score": result.score}
