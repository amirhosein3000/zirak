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

import numpy as np
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


COLUMNS = ("ts", "open", "high", "low", "close", "volume")


class Frame:
    """A read-only, DataFrame-like view of closed candles: `frame["close"]` returns a pandas Series.

    Series are built lazily and cached, which is much cheaper than constructing a full DataFrame on
    every candle (backtests call this thousands of times). `ts` holds unix seconds; it's exposed as
    UTC datetimes.
    """

    def __init__(self, arrays: dict[str, np.ndarray]) -> None:
        self._arrays = arrays
        self._series: dict[str, pd.Series] = {}

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> Frame:
        arrays = {c: df[c].to_numpy() for c in COLUMNS if c in df and c != "ts"}
        if "ts" in df:
            arrays["ts"] = (pd.to_datetime(df["ts"], utc=True).astype("int64") // 10**9).to_numpy()
        return cls(arrays)

    def __len__(self) -> int:
        return len(self._arrays["close"])

    def __contains__(self, name: str) -> bool:
        return name in self._arrays

    def __getitem__(self, name: str) -> pd.Series:
        if name not in self._series:
            arr = self._arrays[name]
            if name == "ts":
                self._series[name] = pd.Series(pd.to_datetime(arr, unit="s", utc=True))
            else:
                self._series[name] = pd.Series(arr, dtype=float)
        return self._series[name]

    def last(self, name: str) -> float:
        return float(self._arrays[name][-1])


@dataclass
class StrategyContext:
    """Everything a strategy may look at. `df` holds only *closed* candles (no look-ahead)."""

    symbol: str
    market: Market
    resolution: str
    now: datetime
    df: Frame
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
        return self.df.last("close")


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
