"""Where market data comes from: the recorder's SQLite DB when it has the series, else the sample CSVs."""

from __future__ import annotations

from zirak.config import Settings
from zirak.data.store import Store, load_candle_dir
from zirak.exchange.replay import ReplayExchange
from zirak.models import Candle


def build_replay(settings: Settings) -> tuple[ReplayExchange, str]:
    """A ReplayExchange over recorded data if available, otherwise the bundled sample. Returns (replay, label)."""
    candles = load_candle_dir(settings.replay_dir) if settings.replay_dir.exists() else {}
    label = "sample"
    books = {}
    if settings.db_path.exists():
        store = Store(settings.db_path)
        try:
            for symbol, resolution, count, _first, _last in store.stats():
                if count >= 100:
                    candles[(symbol, resolution)] = store.load_candles(symbol, resolution)
                    label = "recorded"
            for symbol in settings.markets:
                b = store.load_books(symbol)
                if b:
                    books[symbol] = b
        finally:
            store.close()
    return ReplayExchange(candles, books), label


def load_series(replay: ReplayExchange, symbol: str, resolution: str) -> list[Candle]:
    series = replay.series(symbol, resolution)
    if not series:
        raise LookupError(f"no {resolution} candles for {symbol}")
    return series
