"""Core domain types. Money values are always `Decimal`; timestamps are always UTC-aware."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum
from typing import Any

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)

# Our own resolution names. Exchange adapters map them to the exchange's format.
RESOLUTION_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def resolution_delta(resolution: str) -> timedelta:
    return timedelta(seconds=RESOLUTION_SECONDS[resolution])


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"

    @property
    def is_open(self) -> bool:
        return self in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round down to a multiple of `step` (e.g. quantity precision)."""
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


@dataclass(frozen=True)
class Market:
    symbol: str
    base: str
    quote: str
    price_step: Decimal
    qty_step: Decimal
    min_qty: Decimal
    min_notional: Decimal  # minimum order value in quote currency
    verified: bool = False  # True once precision/minimums come from the exchange API

    def round_qty(self, qty: Decimal) -> Decimal:
        return floor_to_step(qty, self.qty_step)

    def round_price(self, price: Decimal, side: Side | None = None) -> Decimal:
        """Round a price to the tick size. With a side, round *against* us (buy up, sell down)."""
        if side is Side.BUY:
            return ceil_to_step(price, self.price_step)
        if side is Side.SELL:
            return floor_to_step(price, self.price_step)
        return (price / self.price_step).quantize(ONE) * self.price_step

    def check_order(self, qty: Decimal, price: Decimal) -> str | None:
        """Return a reason string if (qty, price) violates the market's limits, else None."""
        if qty <= 0:
            return "qty_not_positive"
        if qty != self.round_qty(qty):
            return "qty_precision"
        if qty < self.min_qty:
            return "below_min_qty"
        if qty * price < self.min_notional:
            return "below_min_notional"
        return None


@dataclass(frozen=True)
class Candle:
    ts: datetime  # open time, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
        }


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    qty: Decimal


@dataclass(frozen=True)
class OrderBook:
    symbol: str
    ts: datetime
    bids: list[BookLevel]  # best (highest) first
    asks: list[BookLevel]  # best (lowest) first
    synthetic: bool = False  # True when generated from candles, not recorded from the exchange

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2


@dataclass(frozen=True)
class PublicTrade:
    symbol: str
    ts: datetime
    price: Decimal
    qty: Decimal
    side: Side | None


@dataclass(frozen=True)
class Balance:
    asset: str
    free: Decimal
    locked: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Side
    type: OrderType
    qty: Decimal
    price: Decimal | None = None  # required for limit orders
    client_tag: str = ""


@dataclass
class Order:
    id: str
    symbol: str
    side: Side
    type: OrderType
    qty: Decimal
    price: Decimal | None
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    filled_qty: Decimal = ZERO
    quote_filled: Decimal = ZERO  # sum(price * qty) of fills, before fees
    fee: Decimal = ZERO
    fee_asset: str = ""
    client_tag: str = ""
    reject_reason: str = ""
    fills: list[Fill] = field(default_factory=list)

    @property
    def avg_price(self) -> Decimal | None:
        if self.filled_qty <= 0:
            return None
        return self.quote_filled / self.filled_qty

    @property
    def remaining(self) -> Decimal:
        return self.qty - self.filled_qty

    def to_dict(self) -> dict[str, Any]:
        avg = self.avg_price
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "type": self.type.value,
            "qty": str(self.qty),
            "price": str(self.price) if self.price is not None else None,
            "status": self.status.value,
            "filled_qty": str(self.filled_qty),
            "avg_price": str(avg) if avg is not None else None,
            "fee": str(self.fee),
            "fee_asset": self.fee_asset,
            "client_tag": self.client_tag,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: Side
    price: Decimal
    qty: Decimal
    fee: Decimal
    fee_asset: str
    ts: datetime
    is_maker: bool
