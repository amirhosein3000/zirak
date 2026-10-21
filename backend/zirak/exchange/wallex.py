"""Real Wallex client.

BLOCKED: docs/wallex-api/ is not in the repo yet, so no endpoint, field or channel is implemented.
We never write exchange calls from memory. Every method raises `NotImplementedError` until the docs
are added; private (account/order) methods run the live-trading guard *first*, so with
LIVE_TRADING=false they fail with `LiveTradingDisabled` before anything else happens.

There is deliberately no withdrawal or transfer method, and there must never be one.
"""

from __future__ import annotations

from datetime import datetime

from zirak.config import Settings
from zirak.exchange.base import ExchangeClient
from zirak.exchange.guard import require_live
from zirak.models import Balance, Candle, Market, Order, OrderBook, OrderRequest, PublicTrade

_MISSING_DOCS = "WallexClient is waiting for docs/wallex-api (UNVERIFIED: no endpoints implemented)"


class WallexClient(ExchangeClient):
    name = "wallex"
    is_real = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---- public market data ----------------------------------------------------------------
    async def get_markets(self) -> list[Market]:
        raise NotImplementedError(_MISSING_DOCS)

    async def get_candles(
        self, symbol: str, resolution: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        raise NotImplementedError(_MISSING_DOCS)

    async def get_order_book(self, symbol: str) -> OrderBook:
        raise NotImplementedError(_MISSING_DOCS)

    async def get_recent_trades(self, symbol: str) -> list[PublicTrade]:
        raise NotImplementedError(_MISSING_DOCS)

    # ---- private: guarded ----------------------------------------------------------------------
    async def get_balances(self) -> dict[str, Balance]:
        require_live(self.settings, risk_reducing=True)
        raise NotImplementedError(_MISSING_DOCS)

    async def place_order(self, req: OrderRequest) -> Order:
        require_live(self.settings)
        raise NotImplementedError(_MISSING_DOCS)

    async def cancel_order(self, symbol: str, order_id: str) -> Order:
        # Cancelling reduces risk, so it works while the kill switch is engaged, but still needs live mode.
        require_live(self.settings, risk_reducing=True)
        raise NotImplementedError(_MISSING_DOCS)

    async def get_order(self, symbol: str, order_id: str) -> Order:
        require_live(self.settings, risk_reducing=True)
        raise NotImplementedError(_MISSING_DOCS)

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        require_live(self.settings, risk_reducing=True)
        raise NotImplementedError(_MISSING_DOCS)
