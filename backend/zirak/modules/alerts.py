"""Alerts: price / RSI / bot-PnL conditions, checked every ALERTS_INTERVAL_S (and on demand).

Delivered in-app (the events list) and, when configured, to a Telegram and/or Bale bot. Bale's bot
API mirrors Telegram's `sendMessage` at https://tapi.bale.ai. Alerts are stored in
`<DATA_DIR>/alerts.json`. Alerts never trade: they only notify.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from zirak.config import Settings
from zirak.i18n import fa_num, fa_pct
from zirak.indicators import candles_to_df, last, rsi
from zirak.models import utcnow

Kind = Literal["price_above", "price_below", "rsi_above", "rsi_below", "pnl_below_pct"]
KIND_FA = {
    "price_above": "قیمت بالاتر از",
    "price_below": "قیمت پایین‌تر از",
    "rsi_above": "RSI بالاتر از",
    "rsi_below": "RSI پایین‌تر از",
    "pnl_below_pct": "سود/زیان ربات کمتر از (٪)",
}
TELEGRAM_API = "https://api.telegram.org"
BALE_API = "https://tapi.bale.ai"


@dataclass
class Alert:
    id: str
    symbol: str
    kind: str
    value: float
    once: bool = True
    active: bool = True
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    last_fired: str | None = None


@dataclass(frozen=True)
class Event:
    alert_id: str
    ts: str
    message_fa: str
    channels: list[str]


def condition_met(kind: str, value: float, observed: float | None) -> bool:
    if observed is None:
        return False
    if kind in ("price_above", "rsi_above"):
        return observed > value
    return observed < value  # price_below, rsi_below, pnl_below_pct


def message_for(alert: Alert, observed: float) -> str:
    what = KIND_FA.get(alert.kind, alert.kind)
    shown = fa_pct(observed, 2) if alert.kind == "pnl_below_pct" else fa_num(observed, 2)
    return f"🔔 زیرک: هشدار {alert.symbol} — {what} {fa_num(alert.value, 2)} (اکنون {shown}). این توصیهٔ مالی نیست."


class AlertBook:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.alerts: dict[str, Alert] = {}
        self.events: list[Event] = []
        if path.exists():
            try:
                for row in json.loads(path.read_text(encoding="utf-8")):
                    a = Alert(**row)
                    self.alerts[a.id] = a
            except (ValueError, TypeError):
                self.alerts = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [asdict(a) for a in self.alerts.values()]
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, symbol: str, kind: str, value: float, once: bool) -> Alert:
        a = Alert(secrets.token_hex(4), symbol, kind, value, once)
        self.alerts[a.id] = a
        self.save()
        return a

    def remove(self, alert_id: str) -> bool:
        found = self.alerts.pop(alert_id, None) is not None
        self.save()
        return found


async def notify(
    settings: Settings, text: str, transport: httpx.AsyncBaseTransport | None = None
) -> list[str]:
    """Send to every configured external channel. Returns the channels that accepted the message."""
    targets = [
        ("telegram", TELEGRAM_API, settings.alerts_telegram_token, settings.alerts_telegram_chat_id),
        ("bale", BALE_API, settings.alerts_bale_token, settings.alerts_bale_chat_id),
    ]
    sent: list[str] = ["in_app"]
    async with httpx.AsyncClient(timeout=10, transport=transport) as client:
        for name, base, token, chat in targets:
            if not token or not chat:
                continue
            try:
                r = await client.post(f"{base}/bot{token}/sendMessage", json={"chat_id": chat, "text": text})
                if r.status_code < 400:
                    sent.append(name)
            except httpx.HTTPError:
                continue
    return sent


async def observe(state: Any, alert: Alert) -> float | None:
    if alert.kind == "pnl_below_pct":
        bot = state.runner.bot
        if bot is None:
            return None
        snap = await bot.snapshot()
        return float(snap["pnl_pct"])
    candles = await state.candles(alert.symbol, "1h", 100)
    if not candles:
        return None
    if alert.kind.startswith("price"):
        return float(candles[-1].close)
    return last(rsi(candles_to_df(candles)["close"], 14))


async def check_all(
    state: Any, book: AlertBook, transport: httpx.AsyncBaseTransport | None = None
) -> list[Event]:
    fired: list[Event] = []
    for alert in [a for a in book.alerts.values() if a.active]:
        try:
            observed = await observe(state, alert)
        except Exception:
            continue  # one broken data source must not stop the other alerts
        if observed is None or not condition_met(alert.kind, alert.value, observed):
            continue
        text = message_for(alert, observed)
        channels = await notify(state.settings, text, transport)
        ev = Event(alert.id, utcnow().isoformat(), text, channels)
        book.events.append(ev)
        fired.append(ev)
        alert.last_fired = ev.ts
        if alert.once:
            alert.active = False
    book.events = book.events[-100:]
    if fired:
        book.save()
    return fired


# ---- API ---------------------------------------------------------------------------------------
router = APIRouter()


def _book(state: Any) -> AlertBook:
    if not hasattr(state, "alert_book"):
        state.alert_book = AlertBook(state.settings.data_dir / "alerts.json")
    book: AlertBook = state.alert_book
    _ensure_loop(state, book)
    return book


def _ensure_loop(state: Any, book: AlertBook) -> None:
    interval = state.settings.alerts_interval_s
    task = getattr(state, "alert_task", None)
    if interval <= 0 or (task is not None and not task.done()):
        return

    async def loop() -> None:
        while True:
            await asyncio.sleep(interval)
            await check_all(state, book)

    state.alert_task = asyncio.get_running_loop().create_task(loop())


class AlertIn(BaseModel):
    symbol: str = "BTCTMN"
    kind: Kind
    value: float
    once: bool = True


@router.get("")
async def list_alerts(request: Request) -> dict[str, Any]:
    state = request.app.state.zirak
    book = _book(state)
    s: Settings = state.settings
    return {
        "alerts": [asdict(a) for a in book.alerts.values()],
        "events": [asdict(e) for e in reversed(book.events)],
        "channels": {
            "telegram": bool(s.alerts_telegram_token and s.alerts_telegram_chat_id),
            "bale": bool(s.alerts_bale_token and s.alerts_bale_chat_id),
        },
        "kinds_fa": KIND_FA,
    }


@router.post("")
async def add_alert(body: AlertIn, request: Request) -> dict[str, Any]:
    state = request.app.state.zirak
    if body.kind != "pnl_below_pct" and await state.market(body.symbol) is None:
        raise HTTPException(404, "بازار پیدا نشد")
    return asdict(_book(state).add(body.symbol, body.kind, body.value, body.once))


@router.delete("/{alert_id}")
async def delete_alert(alert_id: str, request: Request) -> dict[str, Any]:
    return {"deleted": _book(request.app.state.zirak).remove(alert_id)}


@router.post("/check")
async def check(request: Request) -> dict[str, Any]:
    state = request.app.state.zirak
    return {"fired": [asdict(e) for e in await check_all(state, _book(state))]}
