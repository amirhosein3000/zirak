"""Market-data recorder and history backfill (Wallex public REST, docs/wallex-api/market-data.md).

The recorder is built to run for days. Each task (candles, book snapshots, trades) runs on its own
interval, catches its own errors with backoff, and writes a small status file
(`<DATA_DIR>/recorder_status.json`) so you can check that it's alive. It uses REST polling because
that's the path verified to work from this machine; the WebSocket v2 handshake was unreliable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from zirak.data.store import Store
from zirak.exchange.wallex import WallexClient
from zirak.models import OrderBook, resolution_delta, utcnow

log = logging.getLogger("zirak.recorder")

BOOK_LEVELS = 20  # keep the DB small enough to run for days


@dataclass
class TaskStatus:
    runs: int = 0
    errors: int = 0
    rows: int = 0
    last_ok: str | None = None
    last_error: str | None = None


@dataclass
class RecorderStatus:
    started_at: str = field(default_factory=lambda: utcnow().isoformat())
    tasks: dict[str, TaskStatus] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "updated_at": utcnow().isoformat(),
            "tasks": {k: v.__dict__ for k, v in self.tasks.items()},
        }


def trim_book(book: OrderBook, levels: int = BOOK_LEVELS) -> OrderBook:
    return OrderBook(book.symbol, book.ts, book.bids[:levels], book.asks[:levels], book.synthetic)


async def save_markets(client: WallexClient, path: Path) -> int:
    """Snapshot of spot market metadata (precision etc.) so offline replays use the real values."""
    raw = await client.raw_markets()
    keep = (
        "symbol",
        "base_asset",
        "quote_asset",
        "amount_precision",
        "price_precision",
        "is_spot",
        "fa_base_asset",
        "fa_quote_asset",
        "is_zero_fee",
    )
    rows = [{k: m.get(k) for k in keep} for m in raw if m.get("is_spot")]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"saved_at": utcnow().isoformat(), "markets": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return len(rows)


async def backfill(
    client: WallexClient,
    store: Store,
    symbols: list[str],
    days: dict[str, float],
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Download history for each symbol/resolution (native 1m/1h/1d) into the store."""
    counts: dict[str, int] = {}
    now = utcnow()
    for symbol in symbols:
        for res, d in days.items():
            if d <= 0:
                continue
            candles = await client.get_candles(symbol, res, now - timedelta(days=d), now)
            n = store.save_candles(symbol, res, candles)
            counts[f"{symbol}_{res}"] = n
            first = candles[0].ts.isoformat() if candles else "-"
            progress(f"  {symbol:8s} {res:3s} {n:6d} candles from {first}")
    return counts


class Recorder:
    def __init__(
        self,
        client: WallexClient,
        store: Store,
        symbols: list[str],
        resolutions: list[str],
        candle_interval_s: float,
        book_interval_s: float,
        trades_interval_s: float,
        status_path: Path,
    ) -> None:
        self.client = client
        self.store = store
        self.symbols = symbols
        self.resolutions = resolutions
        self.intervals = {"candles": candle_interval_s, "book": book_interval_s, "trades": trades_interval_s}
        self.status = RecorderStatus()
        self.status_path = status_path

    # ---- one pass of each task ---------------------------------------------------------------
    async def record_candles(self) -> int:
        rows, now = 0, utcnow()
        for symbol in self.symbols:
            for res in self.resolutions:
                last = self.store.last_candle_ts(symbol, res)
                # Re-fetch a little overlap; INSERT OR REPLACE makes it idempotent.
                start = (last - resolution_delta(res) * 2) if last else now - timedelta(days=2)
                candles = await self.client.get_candles(symbol, res, start, now)
                rows += self.store.save_candles(symbol, res, candles)
        return rows

    async def record_book(self) -> int:
        for symbol in self.symbols:
            self.store.save_book(trim_book(await self.client.get_order_book(symbol)))
        return len(self.symbols)

    async def record_trades(self) -> int:
        return sum([self.store.save_trades(await self.client.get_recent_trades(s)) for s in self.symbols])

    # ---- loop ------------------------------------------------------------------------------------
    async def _task_loop(self, name: str, fn: Callable[[], Awaitable[int]], stop_at: datetime | None) -> None:
        st = self.status.tasks.setdefault(name, TaskStatus())
        backoff = 5.0
        while stop_at is None or utcnow() < stop_at:
            try:
                st.rows += await fn()
                st.runs += 1
                st.last_ok = utcnow().isoformat()
                backoff = 5.0
                delay = self.intervals[name]
            except Exception as e:
                st.errors += 1
                st.last_error = f"{utcnow().isoformat()} {type(e).__name__}: {e}"[:300]
                log.warning("recorder %s failed: %s", name, st.last_error)
                delay, backoff = backoff, min(backoff * 2, 300.0)
            self.write_status()
            if stop_at is not None:
                delay = min(delay, max(0.0, (stop_at - utcnow()).total_seconds()))
            await asyncio.sleep(delay)

    def write_status(self) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps(self.status.to_dict(), indent=1), encoding="utf-8")

    async def run(self, duration_s: float | None = None) -> RecorderStatus:
        stop_at = utcnow() + timedelta(seconds=duration_s) if duration_s else None
        await asyncio.gather(
            self._task_loop("candles", self.record_candles, stop_at),
            self._task_loop("book", self.record_book, stop_at),
            self._task_loop("trades", self.record_trades, stop_at),
        )
        return self.status
