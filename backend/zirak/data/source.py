"""Where offline market data comes from.

Priority: the recorder's SQLite DB (series with >= 100 candles) over the CSV directory `REPLAY_DIR`
(default: the real Wallex sample in tests/fixtures/wallex). 15m and 4h series are derived from 1m and 1h
when they aren't stored. Market precision comes from a `markets.json` snapshot when one exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from zirak.config import Settings
from zirak.data.aggregate import DERIVED_FROM, aggregate
from zirak.data.store import Store, load_candle_dir
from zirak.exchange.replay import ReplayExchange
from zirak.markets import DEFAULT_MARKETS, load_markets_file
from zirak.models import Candle, Market, OrderBook, resolution_delta


def is_synthetic(directory: Path) -> bool:
    readme = directory / "README.md"
    return readme.exists() and "SYNTHETIC" in readme.read_text(encoding="utf-8")


def load_markets(settings: Settings) -> dict[str, Market]:
    markets = dict(DEFAULT_MARKETS)
    for path in (settings.replay_dir / "markets.json", settings.data_dir / "markets.json"):
        markets.update(load_markets_file(path))
    return markets


def add_derived(candles: dict[tuple[str, str], list[Candle]]) -> None:
    """Fill in 5m/15m/4h series from their base resolution when they're missing."""
    for (symbol, res), series in list(candles.items()):
        for derived, base in DERIVED_FROM.items():
            if base == res and (symbol, derived) not in candles and series:
                until = series[-1].ts + resolution_delta(res)
                candles[(symbol, derived)] = aggregate(series, derived, until=until)


def build_replay(settings: Settings) -> tuple[ReplayExchange, str]:
    """A ReplayExchange over recorded data. Returns (replay, label) with label "recorded" or "synthetic"."""
    candles = load_candle_dir(settings.replay_dir) if settings.replay_dir.exists() else {}
    label = "synthetic" if is_synthetic(settings.replay_dir) else "recorded"
    books: dict[str, list[OrderBook]] = {}
    if settings.db_path.exists():
        store = Store(settings.db_path)
        try:
            for symbol, resolution, count, _first, _last in store.stats():
                if count >= 100:
                    candles[(symbol, resolution)] = store.load_candles(symbol, resolution)
                    label = "recorded"
            since = datetime.now(UTC) - timedelta(days=2)
            for symbol in settings.markets:
                b = [x for x in store.load_books(symbol) if x.ts >= since]
                if b:
                    books[symbol] = b
        finally:
            store.close()
    add_derived(candles)
    return ReplayExchange(candles, books, markets=load_markets(settings)), label


def load_series(replay: ReplayExchange, symbol: str, resolution: str) -> list[Candle]:
    series = replay.series(symbol, resolution)
    if not series:
        raise LookupError(f"no {resolution} candles for {symbol}")
    return series
