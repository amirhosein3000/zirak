"""Executor: turns an approved RiskDecision into an order on whichever ExchangeClient is active."""

from __future__ import annotations

from decimal import Decimal

from zirak.config import Settings
from zirak.engine.risk import RiskDecision
from zirak.exchange.base import ExchangeClient
from zirak.exchange.guard import LiveTradingDisabled, check_hard_limits, require_live
from zirak.models import Market, Order, OrderRequest
from zirak.strategy.base import Signal


class Executor:
    def __init__(self, exchange: ExchangeClient, market: Market, settings: Settings | None = None) -> None:
        self.exchange = exchange
        self.market = market
        self.settings = settings

    async def execute(
        self, signal: Signal, decision: RiskDecision, ref_price: Decimal, tag: str
    ) -> Order | None:
        if not decision.approved or decision.qty <= 0:
            return None
        price = None
        if signal.limit_price is not None:
            price = self.market.round_price(signal.limit_price, signal.side)
        req = OrderRequest(self.market.symbol, signal.side, signal.order_type, decision.qty, price, tag)
        if self.exchange.is_real:
            # Belt and braces: the real client guards itself too.
            if self.settings is None:
                raise LiveTradingDisabled("no settings given for a real exchange")
            require_live(self.settings)
            check_hard_limits(self.settings, self.market, req, ref_price)
        return await self.exchange.place_order(req)
