"""The `ExchangeClient` interface every exchange implementation follows.

Implementations:
- `WallexClient`  (exchange/wallex.py): the real exchange. Private calls are guarded by exchange/guard.py.
- `PaperExchange` (exchange/paper.py): simulated fills on top of any market-data client.
- `ReplayExchange`(exchange/replay.py): recorded market data, replayed deterministically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from zirak.models import Balance, Candle, Market, Order, OrderBook, OrderRequest, PublicTrade


@dataclass(frozen=True)
class MarketEvent:
    """One item from `ExchangeClient.stream`."""

    kind: str  # "candle" | "book" | "trade"
    symbol: str
    candle: Candle | None = None
    book: OrderBook | None = None
    trade: PublicTrade | None = None


class ExchangeClient(ABC):
    name: str = "base"
    #: True only for clients that can move real money. Used by the safety guard and the UI.
    is_real: bool = False

    # ---- market data -----------------------------------------------------------------------
    @abstractmethod
    async def get_markets(self) -> list[Market]: ...

    @abstractmethod
    async def get_candles(
        self, symbol: str, resolution: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        """Closed candles in [start, end), oldest first."""

    @abstractmethod
    async def get_order_book(self, symbol: str) -> OrderBook: ...

    @abstractmethod
    async def get_recent_trades(self, symbol: str) -> list[PublicTrade]: ...

    def stream(self, symbols: list[str]) -> AsyncIterator[MarketEvent]:
        """Live market events. Optional: callers fall back to polling when not implemented."""
        raise NotImplementedError(f"{self.name} has no live stream")

    # ---- account / trading -------------------------------------------------------------------
    @abstractmethod
    async def get_balances(self) -> dict[str, Balance]: ...

    @abstractmethod
    async def place_order(self, req: OrderRequest) -> Order: ...

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> Order: ...

    @abstractmethod
    async def get_order(self, symbol: str, order_id: str) -> Order: ...

    @abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[Order]: ...

    async def cancel_all(self, symbol: str | None = None) -> list[Order]:
        """Cancel every open order (used by the kill switch). Keeps going if one cancel fails."""
        canceled: list[Order] = []
        for order in await self.get_open_orders(symbol):
            try:
                canceled.append(await self.cancel_order(order.symbol, order.id))
            except Exception:
                continue
        return canceled

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Release network resources."""
