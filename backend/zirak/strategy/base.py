"""Strategy interface. A strategy only *proposes* signals; RiskManager decides, Executor acts.

To add a strategy: subclass `Strategy`, implement `on_candle` (and optionally `on_book`), give it a
unique `key`, and register it in `zirak/strategy/registry.py`. See CLAUDE.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

import pandas as pd

from zirak.models import ZERO, Market, OrderBook, OrderType, Side


@dataclass(frozen=True)
class Signal:
    side: Side
    #: BUY: % of current equity to put in. SELL: % of the current position to sell.
    size_pct: Decimal
    reason: str  # short machine code, e.g. "ema_cross_up"
    note_fa: str  # one Persian sentence a user can read
    indicators: dict[str, float] = field(default_factory=dict)
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None


@dataclass
class StrategyContext:
    """Everything a strategy may look at. `df` holds only *closed* candles (no look-ahead)."""

    symbol: str
    market: Market
    resolution: str
    now: datetime
    df: pd.DataFrame
    position_qty: Decimal = ZERO
    avg_entry: Decimal | None = None
    entries: int = 0  # buys since the position was last flat
    equity: Decimal = ZERO
    quote_free: Decimal = ZERO

    @property
    def in_position(self) -> bool:
        return self.position_qty > 0 and self.position_qty >= self.market.min_qty

    @property
    def close(self) -> float:
        return float(self.df["close"].iloc[-1])


class Strategy(ABC):
    key: ClassVar[str] = "base"
    title_fa: ClassVar[str] = ""
    description_fa: ClassVar[str] = ""
    #: candles needed before the strategy can say anything useful
    warmup: int = 1

    def __init__(self, **params: Any) -> None:
        self.params = params

    @abstractmethod
    def on_candle(self, ctx: StrategyContext) -> list[Signal]: ...

    def on_book(self, ctx: StrategyContext, book: OrderBook) -> list[Signal]:
        return []

    def describe(self) -> dict[str, Any]:
        return {"key": self.key, "title_fa": self.title_fa, "params": self.params}
