"""SQLite storage for recorded market data. Prices and quantities are stored as TEXT to keep Decimals exact.

CSV fixtures (tests/fixtures/sample) use the same columns, one file per `{SYMBOL}_{resolution}.csv`.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from zirak.models import BookLevel, Candle, OrderBook, PublicTrade, Side, ensure_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL, resolution TEXT NOT NULL, ts TEXT NOT NULL,
    open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL, volume TEXT NOT NULL,
    PRIMARY KEY (symbol, resolution, ts)
);
CREATE TABLE IF NOT EXISTS book_snapshots (
    symbol TEXT NOT NULL, ts TEXT NOT NULL, bids TEXT NOT NULL, asks TEXT NOT NULL,
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS trades (
    symbol TEXT NOT NULL, ts TEXT NOT NULL, price TEXT NOT NULL, qty TEXT NOT NULL, side TEXT,
    PRIMARY KEY (symbol, ts, price, qty)
);
"""


def _ts(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value))


def _levels(raw: str) -> list[BookLevel]:
    return [BookLevel(Decimal(p), Decimal(q)) for p, q in json.loads(raw)]


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- writes ----------------------------------------------------------------------------
    def save_candles(self, symbol: str, resolution: str, candles: Iterable[Candle]) -> int:
        rows = [
            (
                symbol,
                resolution,
                c.ts.isoformat(),
                str(c.open),
                str(c.high),
                str(c.low),
                str(c.close),
                str(c.volume),
            )
            for c in candles
        ]
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def save_book(self, book: OrderBook) -> None:
        bids = json.dumps([[str(lv.price), str(lv.qty)] for lv in book.bids])
        asks = json.dumps([[str(lv.price), str(lv.qty)] for lv in book.asks])
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO book_snapshots VALUES (?,?,?,?)",
                (book.symbol, book.ts.isoformat(), bids, asks),
            )

    def save_trades(self, trades: Iterable[PublicTrade]) -> int:
        rows = [
            (t.symbol, t.ts.isoformat(), str(t.price), str(t.qty), t.side.value if t.side else None)
            for t in trades
        ]
        before = self.conn.total_changes
        with self.conn:
            self.conn.executemany("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?)", rows)
        return self.conn.total_changes - before  # only genuinely new trades

    # ---- reads -----------------------------------------------------------------------------
    def load_candles(
        self, symbol: str, resolution: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        sql = "SELECT ts, open, high, low, close, volume FROM candles WHERE symbol=? AND resolution=?"
        args: list[str] = [symbol, resolution]
        if start is not None:
            sql += " AND ts >= ?"
            args.append(start.isoformat())
        if end is not None:
            sql += " AND ts < ?"
            args.append(end.isoformat())
        sql += " ORDER BY ts"
        return [
            Candle(_ts(r[0]), Decimal(r[1]), Decimal(r[2]), Decimal(r[3]), Decimal(r[4]), Decimal(r[5]))
            for r in self.conn.execute(sql, args)
        ]

    def last_candle_ts(self, symbol: str, resolution: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT MAX(ts) FROM candles WHERE symbol=? AND resolution=?", (symbol, resolution)
        ).fetchone()
        return _ts(row[0]) if row and row[0] else None

    def load_books(self, symbol: str) -> list[OrderBook]:
        rows = self.conn.execute(
            "SELECT ts, bids, asks FROM book_snapshots WHERE symbol=? ORDER BY ts", (symbol,)
        )
        return [OrderBook(symbol, _ts(r[0]), _levels(r[1]), _levels(r[2])) for r in rows]

    def load_trades(self, symbol: str) -> list[PublicTrade]:
        rows = self.conn.execute(
            "SELECT ts, price, qty, side FROM trades WHERE symbol=? ORDER BY ts", (symbol,)
        )
        return [
            PublicTrade(symbol, _ts(r[0]), Decimal(r[1]), Decimal(r[2]), Side(r[3]) if r[3] else None)
            for r in rows
        ]

    def stats(self) -> list[tuple[str, str, int, str, str]]:
        """(symbol, resolution, count, first_ts, last_ts) for every candle series."""
        return list(
            self.conn.execute(
                "SELECT symbol, resolution, COUNT(*), MIN(ts), MAX(ts) FROM candles "
                "GROUP BY symbol, resolution ORDER BY symbol, resolution"
            )
        )


# ---- CSV fixtures --------------------------------------------------------------------------------
CSV_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]


def write_candles_csv(path: Path, candles: Iterable[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for c in candles:
            w.writerow([c.ts.isoformat(), c.open, c.high, c.low, c.close, c.volume])


def read_candles_csv(path: Path) -> list[Candle]:
    with path.open(encoding="utf-8") as f:
        return [
            Candle(
                _ts(r["ts"]),
                Decimal(r["open"]),
                Decimal(r["high"]),
                Decimal(r["low"]),
                Decimal(r["close"]),
                Decimal(r["volume"]),
            )
            for r in csv.DictReader(f)
        ]


def load_candle_dir(directory: Path) -> dict[tuple[str, str], list[Candle]]:
    """Load every `{SYMBOL}_{resolution}.csv` in a directory."""
    out: dict[tuple[str, str], list[Candle]] = {}
    for path in sorted(directory.glob("*_*.csv")):
        symbol, resolution = path.stem.rsplit("_", 1)
        out[(symbol, resolution)] = read_candles_csv(path)
    return out
