"""PaperExchange: simulated trading on top of any market-data client (live Wallex data or a replay).

Fill model
----------
- Candle mode (`on_candle`, used by backtests and replays): an order placed after candle *t* closed is
  matched against candle *t+1*. Market orders fill at t+1's open moved by `slippage_bps`. A limit order
  that is marketable when it arrives (buy: open <= limit) takes liquidity like a market order, but never
  beyond its limit, and pays the taker fee. Otherwise it rests and fills, as maker at its own limit
  price, only when a later candle trades *through* it (buy: low < price, sell: high > price): a gap past
  a resting order fills at the order's price, never at the better open. All orders on one candle share
  `participation` x the candle's volume (unlimited when the candle reports no volume), so big orders
  fill partially.
- Book mode (`on_book`, used for live paper trading): market orders walk the visible book level by
  level (plus `slippage_bps` for latency). A limit order that crosses the book on its first pass takes
  the crossing levels at their prices (taker); later passes fill it as maker at its limit price.
- Market orders are immediate-or-cancel: whatever cannot be filled on the next event is canceled.
  Limit orders keep resting until filled or canceled.
- Fees follow `zirak.fees` (taker for market orders, maker for resting limit orders).
- Funds are reserved when an order is placed and released on fill/cancel, so balances never go negative.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from zirak.exchange.base import ExchangeClient
from zirak.fees import BPS, FeeModel, apply_slippage, fill_amounts
from zirak.models import (
    ONE,
    ZERO,
    Balance,
    Candle,
    Fill,
    Market,
    Order,
    OrderBook,
    OrderRequest,
    OrderStatus,
    OrderType,
    PublicTrade,
    Side,
    utcnow,
)

# Extra quote reserved for market buys on top of slippage, so a gap up does not leave a fill unfunded.
MARKET_BUY_BUFFER = Decimal("0.01")


class PaperExchange(ExchangeClient):
    name = "paper"
    is_real = False

    def __init__(
        self,
        data: ExchangeClient,
        markets: dict[str, Market],
        fees: FeeModel,
        slippage_bps: Decimal,
        balances: dict[str, Decimal],
        participation: Decimal = Decimal("0.10"),
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.data = data
        self.markets = markets
        self.fees = fees
        self.slippage_bps = slippage_bps
        self.participation = participation
        self.clock = clock
        self._free: dict[str, Decimal] = {k: Decimal(v) for k, v in balances.items()}
        self._locked: dict[str, Decimal] = dict.fromkeys(balances, ZERO)
        self._orders: dict[str, Order] = {}
        self._reserved: dict[str, Decimal] = {}  # order id -> amount still reserved for it
        self._last_price: dict[str, Decimal] = {}
        self._fill_log: list[Fill] = []
        self._seq = 0
        self._matched: set[str] = set()  # orders that already had one matching pass (now resting)

    # ---- market data: delegated --------------------------------------------------------------
    async def get_markets(self) -> list[Market]:
        return await self.data.get_markets()

    async def get_candles(
        self, symbol: str, resolution: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        return await self.data.get_candles(symbol, resolution, start, end)

    async def get_order_book(self, symbol: str) -> OrderBook:
        return await self.data.get_order_book(symbol)

    async def get_recent_trades(self, symbol: str) -> list[PublicTrade]:
        return await self.data.get_recent_trades(symbol)

    # ---- account -----------------------------------------------------------------------------
    async def get_balances(self) -> dict[str, Balance]:
        assets = set(self._free) | set(self._locked)
        return {a: Balance(a, self._free.get(a, ZERO), self._locked.get(a, ZERO)) for a in sorted(assets)}

    def set_last_price(self, symbol: str, price: Decimal) -> None:
        self._last_price[symbol] = price

    # ---- orders ------------------------------------------------------------------------------
    async def place_order(self, req: OrderRequest) -> Order:
        now = self.clock()
        self._seq += 1
        order = Order(
            id=f"P{self._seq:06d}",
            symbol=req.symbol,
            side=req.side,
            type=req.type,
            qty=req.qty,
            price=req.price,
            status=OrderStatus.NEW,
            created_at=now,
            updated_at=now,
            client_tag=req.client_tag,
        )
        self._orders[order.id] = order
        market = self.markets.get(req.symbol)
        reason = self._validate(req, market)
        if reason is None and market is not None:
            reason = self._reserve(order, market)
        if reason is not None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = reason
        return order

    def _validate(self, req: OrderRequest, market: Market | None) -> str | None:
        if market is None:
            return "unknown_market"
        if req.type is OrderType.LIMIT:
            if req.price is None or req.price <= 0:
                return "limit_price_required"
            if req.price != market.round_price(req.price):
                return "price_precision"
        ref = req.price if req.type is OrderType.LIMIT else self._last_price.get(req.symbol)
        if ref is None:
            return "no_reference_price"
        return market.check_order(req.qty, ref)

    def _reserve(self, order: Order, market: Market) -> str | None:
        if order.side is Side.BUY:
            asset = market.quote
            if order.type is OrderType.LIMIT:
                assert order.price is not None
                amount = order.qty * order.price
            else:
                ref = self._last_price[order.symbol]
                amount = order.qty * ref * (ONE + self.slippage_bps / BPS + MARKET_BUY_BUFFER)
        else:
            asset, amount = market.base, order.qty
        if self._free.get(asset, ZERO) < amount:
            return "insufficient_balance"
        self._free[asset] = self._free.get(asset, ZERO) - amount
        self._locked[asset] = self._locked.get(asset, ZERO) + amount
        self._reserved[order.id] = amount
        return None

    def _release(self, order: Order) -> None:
        market = self.markets[order.symbol]
        asset = market.quote if order.side is Side.BUY else market.base
        amount = self._reserved.pop(order.id, ZERO)
        self._locked[asset] = self._locked.get(asset, ZERO) - amount
        self._free[asset] = self._free.get(asset, ZERO) + amount

    async def cancel_order(self, symbol: str, order_id: str) -> Order:
        order = self._orders[order_id]
        if order.status.is_open:
            self._release(order)
            order.status = OrderStatus.CANCELED
            order.updated_at = self.clock()
        return order

    async def get_order(self, symbol: str, order_id: str) -> Order:
        return self._orders[order_id]

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        return [
            o for o in self._orders.values() if o.status.is_open and (symbol is None or o.symbol == symbol)
        ]

    def all_orders(self) -> list[Order]:
        return list(self._orders.values())

    # ---- matching ----------------------------------------------------------------------------
    def _apply_fill(
        self, order: Order, price: Decimal, qty: Decimal, is_maker: bool, ts: datetime
    ) -> Decimal:
        """Book one fill. Returns the quantity actually filled (may shrink if funds run out)."""
        market = self.markets[order.symbol]
        qty = market.round_qty(min(qty, order.remaining))
        if order.side is Side.BUY:
            # Never spend more than this order reserved; shrink the fill if the price ran away.
            affordable = market.round_qty(self._reserved.get(order.id, ZERO) / price)
            qty = min(qty, affordable)
        if qty <= 0:
            return ZERO
        amounts = fill_amounts(market, order.side, price, qty, self.fees.rate(is_maker))
        if order.side is Side.BUY:
            cost = -amounts.quote_delta
            self._reserved[order.id] -= cost
            self._locked[market.quote] -= cost
            self._free[market.base] = self._free.get(market.base, ZERO) + amounts.base_delta
        else:
            self._reserved[order.id] -= qty
            self._locked[market.base] -= qty
            self._free[market.quote] = self._free.get(market.quote, ZERO) + amounts.quote_delta
        order.filled_qty += qty
        order.quote_filled += price * qty
        order.fee += amounts.fee
        order.fee_asset = amounts.fee_asset
        order.updated_at = ts
        fill = Fill(
            order.id, order.symbol, order.side, price, qty, amounts.fee, amounts.fee_asset, ts, is_maker
        )
        order.fills.append(fill)
        self._fill_log.append(fill)
        if order.remaining <= 0 or order.remaining < market.min_qty:
            order.status = OrderStatus.FILLED
            self._release(order)
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        return qty

    def _finish_ioc(self, order: Order, ts: datetime) -> None:
        """Market orders do not rest: cancel whatever is left after one matching pass."""
        if order.status.is_open:
            self._release(order)
            order.status = OrderStatus.CANCELED if order.filled_qty == 0 else OrderStatus.FILLED
            if order.filled_qty > 0 and order.remaining > 0:
                order.reject_reason = "partial_fill_remainder_canceled"
            order.updated_at = ts

    def on_candle(self, symbol: str, candle: Candle) -> list[Fill]:
        """Match open orders for `symbol` against a newly closed candle (see module docstring)."""
        fills_before = len(self._fill_log)
        market = self.markets[symbol]
        # Volume shared by every order on this candle. None = the candle carries no volume information.
        capacity: Decimal | None = candle.volume * self.participation if candle.volume > 0 else None
        ts = candle.ts
        for order in [o for o in self._orders.values() if o.symbol == symbol and o.status.is_open]:
            first_pass = order.id not in self._matched
            self._matched.add(order.id)
            if order.created_at > candle.ts and order.type is OrderType.MARKET:
                # Placed after this candle opened (live replay ordering): match on its close instead.
                ref = candle.close
            else:
                ref = candle.open
            room = order.remaining if capacity is None else min(order.remaining, max(capacity, ZERO))
            filled = ZERO
            if order.type is OrderType.MARKET:
                price = apply_slippage(ref, order.side, self.slippage_bps, market)
                filled = self._apply_fill(order, price, room, is_maker=False, ts=ts)
                self._finish_ioc(order, ts)
            else:
                assert order.price is not None
                buy = order.side is Side.BUY
                marketable = candle.open <= order.price if buy else candle.open >= order.price
                if first_pass and marketable:
                    touch = apply_slippage(candle.open, order.side, self.slippage_bps, market)
                    price = min(touch, order.price) if buy else max(touch, order.price)
                    filled = self._apply_fill(order, price, room, is_maker=False, ts=ts)
                elif (buy and candle.low < order.price) or (not buy and candle.high > order.price):
                    filled = self._apply_fill(order, order.price, room, is_maker=True, ts=ts)
            if capacity is not None:
                capacity -= filled
        self._last_price[symbol] = candle.close
        return self._fill_log[fills_before:]

    def on_book(self, book: OrderBook) -> list[Fill]:
        """Match open orders against an order-book snapshot (live paper trading)."""
        fills_before = len(self._fill_log)
        market = self.markets[book.symbol]
        for order in [o for o in self._orders.values() if o.symbol == book.symbol and o.status.is_open]:
            first_pass = order.id not in self._matched
            self._matched.add(order.id)
            levels = book.asks if order.side is Side.BUY else book.bids
            for level in levels:
                if order.remaining <= 0 or not order.status.is_open:
                    break
                touch = apply_slippage(level.price, order.side, self.slippage_bps, market)
                if order.type is OrderType.LIMIT:
                    assert order.price is not None
                    buy = order.side is Side.BUY
                    crosses = level.price <= order.price if buy else level.price >= order.price
                    if not crosses:
                        break
                    if first_pass:  # it took liquidity on arrival: taker at the level, capped by the limit
                        price, maker = (min(touch, order.price) if buy else max(touch, order.price)), False
                    else:  # it was resting and the market came to it
                        price, maker = order.price, True
                else:
                    price, maker = touch, False
                self._apply_fill(order, price, level.qty, is_maker=maker, ts=book.ts)
            if order.type is OrderType.MARKET:
                self._finish_ioc(order, book.ts)
        if book.mid is not None:
            self._last_price[book.symbol] = market.round_price(book.mid)
        return self._fill_log[fills_before:]
