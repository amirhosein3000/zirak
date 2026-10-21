"""ReplayExchange: recorded market data served as if it were live, fully offline and deterministic.

A cursor (UTC time) decides what is visible: only candles that have *closed* by the cursor are
returned, which keeps backtests and replays free of look-ahead. It has no order matching; wrap it in
`PaperExchange` to trade.
"""

from __future__ import annotations

import bisect
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from zirak.data.store import Store, load_candle_dir
from zirak.exchange.base import ExchangeClient
from zirak.markets import DEFAULT_MARKETS
from zirak.models import (
    Balance,
    BookLevel,
    Candle,
    Market,
    Order,
    OrderBook,
    OrderRequest,
    PublicTrade,
    resolution_delta,
)

_NO_ORDERS = "ReplayExchange only serves market data; wrap it in PaperExchange to place orders"


class ReplayExchange(ExchangeClient):
    name = "replay"

    def __init__(
        self,
        candles: dict[tuple[str, str], list[Candle]],
        books: dict[str, list[OrderBook]] | None = None,
        markets: dict[str, Market] | None = None,
    ) -> None:
        self._candles = {k: sorted(v, key=lambda c: c.ts) for k, v in candles.items()}
        self._close_times = {
            (sym, res): [c.ts + resolution_delta(res) for c in series]
            for (sym, res), series in self._candles.items()
        }
        self._books = {k: sorted(v, key=lambda b: b.ts) for k, v in (books or {}).items()}
        self._book_times = {k: [b.ts for b in v] for k, v in self._books.items()}
        self.markets = markets or DEFAULT_MARKETS
        self.cursor: datetime | None = None  # None means "end of data": everything is visible

    @classmethod
    def from_dir(cls, directory: Path) -> ReplayExchange:
        return cls(load_candle_dir(directory))

    @classmethod
    def from_store(cls, store: Store, symbols: list[str], resolutions: list[str]) -> ReplayExchange:
        candles = {(s, r): store.load_candles(s, r) for s in symbols for r in resolutions}
        books = {s: store.load_books(s) for s in symbols}
        return cls({k: v for k, v in candles.items() if v}, {k: v for k, v in books.items() if v})

    # ---- replay control ----------------------------------------------------------------------
    def series(self, symbol: str, resolution: str) -> list[Candle]:
        """The full recorded series (ignores the cursor). For drivers, not for strategies."""
        return self._candles.get((symbol, resolution), [])

    def available(self) -> list[tuple[str, str, int]]:
        return [(s, r, len(v)) for (s, r), v in sorted(self._candles.items())]

    def set_cursor(self, ts: datetime | None) -> None:
        self.cursor = ts

    def visible(self, symbol: str, resolution: str) -> list[Candle]:
        series = self._candles.get((symbol, resolution), [])
        if self.cursor is None:
            return series
        n = bisect.bisect_right(self._close_times[(symbol, resolution)], self.cursor)
        return series[:n]

    def last_close(self, symbol: str) -> Decimal | None:
        best: Candle | None = None
        for (sym, res), _ in self._candles.items():
            if sym != symbol:
                continue
            vis = self.visible(sym, res)
            if vis and (best is None or vis[-1].ts > best.ts):
                best = vis[-1]
        return best.close if best else None

    # ---- ExchangeClient: market data ----------------------------------------------------------
    async def get_markets(self) -> list[Market]:
        symbols = {s for s, _ in self._candles}
        return [m for s, m in self.markets.items() if s in symbols]

    async def get_candles(
        self, symbol: str, resolution: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        return [
            c
            for c in self.visible(symbol, resolution)
            if (start is None or c.ts >= start) and (end is None or c.ts < end)
        ]

    async def get_order_book(self, symbol: str) -> OrderBook:
        books = self._books.get(symbol)
        if books:
            if self.cursor is None:
                return books[-1]
            i = bisect.bisect_right(self._book_times[symbol], self.cursor)
            if i > 0:
                return books[i - 1]
        return self._synthetic_book(symbol)

    async def get_recent_trades(self, symbol: str) -> list[PublicTrade]:
        return []

    def _synthetic_book(self, symbol: str) -> OrderBook:
        """A plausible book around the last close, flagged `synthetic=True` for the UI."""
        candle: Candle | None = None
        for res in ("1m", "5m", "15m", "1h", "4h", "1d"):
            vis = self.visible(symbol, res)
            if vis:
                candle = vis[-1]
                break
        if candle is None:
            raise LookupError(f"no data for {symbol}")
        market = self.markets.get(symbol)
        mid = candle.close
        step = mid * Decimal("0.0005")
        base_qty = max(candle.volume / Decimal(200), Decimal("0.0001"))
        # Tilt depth toward the side the last candle moved, so imbalance carries some information.
        tilt = Decimal("1.3") if candle.close >= candle.open else Decimal("0.77")
        bids, asks = [], []
        for i in range(1, 11):
            bp, ap = mid - step * i, mid + step * i
            if market is not None:
                bp, ap = market.round_price(bp), market.round_price(ap)
                qb, qa = (
                    market.round_qty(base_qty * tilt / i ** Decimal("0.5")),
                    market.round_qty(base_qty / tilt / i ** Decimal("0.5")),
                )
            else:
                qb, qa = base_qty * tilt, base_qty / tilt
            bids.append(BookLevel(bp, qb))
            asks.append(BookLevel(ap, qa))
        ts = self.cursor or (candle.ts + resolution_delta("1m"))
        return OrderBook(symbol, ts, bids, asks, synthetic=True)

    # ---- ExchangeClient: trading (not supported) --------------------------------------------------
    async def get_balances(self) -> dict[str, Balance]:
        raise NotImplementedError(_NO_ORDERS)

    async def place_order(self, req: OrderRequest) -> Order:
        raise NotImplementedError(_NO_ORDERS)

    async def cancel_order(self, symbol: str, order_id: str) -> Order:
        raise NotImplementedError(_NO_ORDERS)

    async def get_order(self, symbol: str, order_id: str) -> Order:
        raise NotImplementedError(_NO_ORDERS)

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        return []
