"""Wallex WebSocket market stream (docs/wallex-api/websocket.md).

v2 (Centrifugo, `wss://api.wallex.ir/connection/websocket`) is tried first. On 2026-10-22 its handshake
often answered HTTP 503 on quick reconnects, so after a few failed attempts we fall back to the
documented, deprecated v1 endpoint (`wss://api.wallex.ir/ws`), which worked reliably. Both send each
depth message as a *full snapshot of one side*, so we keep the latest bid and ask sides and emit a
combined book whenever either changes.

Only public channels are used. The private channel needs a browser-cookie JWT, so order updates are
polled over REST instead.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import websockets

from zirak.config import Settings
from zirak.exchange.base import MarketEvent
from zirak.models import BookLevel, OrderBook, PublicTrade, Side, utcnow

V2_FAILURES_BEFORE_V1 = 3


def _levels(rows: Any) -> list[BookLevel]:
    from zirak.exchange.wallex import D

    return [BookLevel(D(r["price"]), D(r["quantity"])) for r in rows or [] if isinstance(r, dict)]


class _Books:
    """Latest full snapshot of each side per symbol."""

    def __init__(self) -> None:
        self.bids: dict[str, list[BookLevel]] = {}
        self.asks: dict[str, list[BookLevel]] = {}

    def update(self, symbol: str, side: str, rows: Any) -> OrderBook:
        levels = _levels(rows)
        if side == "buyDepth":
            self.bids[symbol] = sorted(levels, key=lambda lv: lv.price, reverse=True)
        else:
            self.asks[symbol] = sorted(levels, key=lambda lv: lv.price)
        return OrderBook(symbol, utcnow(), self.bids.get(symbol, []), self.asks.get(symbol, []))


def parse_channel_message(channel: str, data: Any, books: _Books) -> MarketEvent | None:
    """Turn one channel payload (same body in v1 and v2) into a MarketEvent."""
    from zirak.exchange.wallex import D, _ts

    name = channel.split(":", 1)[-1]  # strip the v2 namespace
    if "@" not in name:
        return None
    symbol, kind = name.split("@", 1)
    if kind == "trade" and isinstance(data, dict):
        side = Side.SELL if data.get("isBuyOrder") else Side.BUY  # maker was a buy -> taker sold
        trade = PublicTrade(
            symbol, _ts(data.get("timestamp")), D(data.get("price")), D(data.get("quantity")), side
        )
        return MarketEvent("trade", symbol, trade=trade)
    if kind in ("buyDepth", "sellDepth"):
        return MarketEvent("book", symbol, book=books.update(symbol, kind, data))
    return None


async def _v2(settings: Settings, symbols: list[str], books: _Books) -> AsyncIterator[MarketEvent]:
    async with websockets.connect(settings.wallex_ws_url, proxy=None, open_timeout=15) as ws:
        await ws.send(json.dumps({"id": 1, "connect": {}}))
        n = 2
        for s in symbols:
            for ch in (f"public:{s}@trade", f"orderbook:{s}@buyDepth", f"orderbook:{s}@sellDepth"):
                await ws.send(json.dumps({"id": n, "subscribe": {"channel": ch}}))
                n += 1
        async for raw in ws:
            for line in str(raw).split("\n"):
                if not line:
                    continue
                if line == "{}":  # server ping: reply with the same empty object
                    await ws.send("{}")
                    continue
                msg = json.loads(line)
                push = msg.get("push") if isinstance(msg, dict) else None
                if push and push.get("pub"):
                    event = parse_channel_message(push["channel"], push["pub"].get("data"), books)
                    if event:
                        yield event


async def _v1(settings: Settings, symbols: list[str], books: _Books) -> AsyncIterator[MarketEvent]:
    async with websockets.connect(settings.wallex_ws_v1_url, proxy=None, open_timeout=15) as ws:
        for s in symbols:
            for ch in (f"{s}@trade", f"{s}@buyDepth", f"{s}@sellDepth"):
                await ws.send(json.dumps(["subscribe", {"channel": ch}]))
        async for raw in ws:
            msg = json.loads(raw)
            if isinstance(msg, list) and len(msg) == 2 and isinstance(msg[0], str):
                event = parse_channel_message(msg[0], msg[1], books)
                if event:
                    yield event
            # dict messages are connection info / errors (see docs); nothing to do


async def stream_events(settings: Settings, symbols: list[str]) -> AsyncIterator[MarketEvent]:
    """Reconnects forever with exponential backoff (v1 also closes every 30 minutes by design)."""
    books = _Books()
    v2_failures = 0
    delay = 2.0
    while True:
        use_v2 = v2_failures < V2_FAILURES_BEFORE_V1
        try:
            source = _v2 if use_v2 else _v1
            async for event in source(settings, symbols, books):
                delay = 2.0
                yield event
        except (OSError, websockets.exceptions.WebSocketException, json.JSONDecodeError, TimeoutError):
            if use_v2:
                v2_failures += 1
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60.0)
