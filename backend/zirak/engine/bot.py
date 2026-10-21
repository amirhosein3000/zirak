"""Bot: one strategy on one market. The same class runs backtests, replays, paper and live trading.

Per closed candle:
  1. (paper) let the PaperExchange match orders placed on the previous candle
  2. sync order fills into the bot's ledger (position, average entry, realised PnL)
  3. RiskManager: roll the day / daily loss limit, then stop-loss & take-profit
  4. Strategy proposes signals (skipped if a risk exit already fired)
  5. RiskManager reviews each signal; Executor places approved orders
  6. log everything (for "why did the bot do that?") and record equity
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from zirak.config import Settings
from zirak.engine.executor import Executor
from zirak.engine.risk import PortfolioView, RiskDecision, RiskManager
from zirak.exchange.base import ExchangeClient
from zirak.exchange.paper import PaperExchange
from zirak.indicators import candles_to_df
from zirak.models import ZERO, Candle, Market, Order, Side, resolution_delta, utcnow
from zirak.strategy.base import Signal, Strategy, StrategyContext


class SimClock:
    """A settable clock so simulated orders get simulated timestamps."""

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or utcnow()

    def __call__(self) -> datetime:
        return self.now


@dataclass
class LogEntry:
    id: int
    ts: datetime
    symbol: str
    side: str
    reason: str
    note_fa: str
    indicators: dict[str, float]
    decision: dict[str, Any]
    price: Decimal
    equity: Decimal
    order_id: str | None = None
    order_status: str | None = None
    filled_qty: Decimal = ZERO
    avg_price: Decimal | None = None
    fee: Decimal = ZERO
    fee_asset: str = ""
    pnl: Decimal | None = None  # realised PnL in quote, for sells
    pnl_pct: Decimal | None = None
    explanation_fa: str | None = None  # cached LLM explanation

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "symbol": self.symbol,
            "side": self.side,
            "reason": self.reason,
            "note_fa": self.note_fa,
            "indicators": self.indicators,
            "decision": self.decision,
            "price": str(self.price),
            "equity": str(self.equity),
            "order_id": self.order_id,
            "order_status": self.order_status,
            "filled_qty": str(self.filled_qty),
            "avg_price": str(self.avg_price) if self.avg_price is not None else None,
            "fee": str(self.fee),
            "fee_asset": self.fee_asset,
            "pnl": str(self.pnl) if self.pnl is not None else None,
            "pnl_pct": str(self.pnl_pct) if self.pnl_pct is not None else None,
            "explanation_fa": self.explanation_fa,
        }


@dataclass
class EquityPoint:
    ts: datetime
    equity: Decimal
    price: Decimal
    position_qty: Decimal


@dataclass
class _Seen:
    filled_qty: Decimal = ZERO
    quote_filled: Decimal = ZERO
    fee: Decimal = ZERO


@dataclass
class Ledger:
    qty: Decimal = ZERO  # base held by this bot (net of fees)
    cost: Decimal = ZERO  # quote paid for `qty`, fees included
    realized: Decimal = ZERO
    entries: int = 0
    exits: list[Decimal] = field(default_factory=list)  # realised PnL of each sell fill batch

    @property
    def avg_entry(self) -> Decimal | None:
        return self.cost / self.qty if self.qty > 0 else None


class Bot:
    def __init__(
        self,
        strategy: Strategy,
        risk: RiskManager,
        exchange: ExchangeClient,
        market: Market,
        resolution: str,
        settings: Settings | None = None,
        clock: SimClock | None = None,
        window: int = 300,
    ) -> None:
        self.strategy = strategy
        self.risk = risk
        self.exchange = exchange
        self.market = market
        self.symbol = market.symbol
        self.resolution = resolution
        self.executor = Executor(exchange, market, settings)
        self.clock = clock
        self.window = max(window, strategy.warmup + 5)
        self.candles: list[Candle] = []
        self.ledger = Ledger()
        self.log: list[LogEntry] = []
        self.equity_curve: list[EquityPoint] = []
        self._seen: dict[str, _Seen] = {}
        self._open: dict[str, LogEntry] = {}  # order id -> log entry, for orders still being filled
        self.stopped = False
        self.last_price: Decimal | None = None

    # ---- main step ---------------------------------------------------------------------------
    async def on_candle(self, candle: Candle) -> None:
        if self.stopped:
            return
        now = candle.ts + resolution_delta(self.resolution)
        if isinstance(self.exchange, PaperExchange):
            self.exchange.on_candle(self.symbol, candle)
        if self.clock is not None:
            self.clock.now = now
        await self.sync_orders()
        self.candles.append(candle)
        if len(self.candles) > self.window * 2:
            self.candles = self.candles[-self.window :]
        self.last_price = candle.close
        view = await self.view(now, candle.close)

        signals = self.risk.on_candle(view) or self.risk.exit_signals(view)
        if not signals:
            ctx = self._context(now, view)
            signals = self.strategy.on_candle(ctx)
        for signal in signals:
            await self._act(signal, view, now)
            view = await self.view(now, candle.close)
        self.equity_curve.append(EquityPoint(now, view.equity, candle.close, self.ledger.qty))

    async def view(self, now: datetime, price: Decimal) -> PortfolioView:
        balances = await self.exchange.get_balances()
        base, quote = balances.get(self.market.base), balances.get(self.market.quote)
        base_total = base.total if base else ZERO
        quote_total = quote.total if quote else ZERO
        return PortfolioView(
            now=now,
            price=price,
            position_qty=min(self.ledger.qty, base_total),
            avg_entry=self.ledger.avg_entry,
            equity=quote_total + base_total * price,
            quote_free=quote.free if quote else ZERO,
            base_free=base.free if base else ZERO,
        )

    def _context(self, now: datetime, view: PortfolioView) -> StrategyContext:
        df: pd.DataFrame = candles_to_df(self.candles[-self.window :])
        return StrategyContext(
            symbol=self.symbol,
            market=self.market,
            resolution=self.resolution,
            now=now,
            df=df,
            position_qty=view.position_qty,
            avg_entry=view.avg_entry,
            entries=self.ledger.entries,
            equity=view.equity,
            quote_free=view.quote_free,
        )

    async def _act(self, signal: Signal, view: PortfolioView, now: datetime) -> None:
        decision: RiskDecision = self.risk.review(signal, view)
        prev = self.log[-1] if self.log else None
        if (
            not decision.approved
            and prev is not None
            and not prev.decision["approved"]
            and prev.reason == signal.reason
            and prev.decision["code"] == decision.code
        ):
            return  # same rejection as last candle: don't flood the log
        entry = LogEntry(
            id=len(self.log) + 1,
            ts=now,
            symbol=self.symbol,
            side=signal.side.value,
            reason=signal.reason,
            note_fa=signal.note_fa,
            indicators=signal.indicators,
            decision=decision.to_dict(),
            price=view.price,
            equity=view.equity,
        )
        self.log.append(entry)
        if not decision.approved:
            return
        order = await self.executor.execute(signal, decision, view.price, tag=f"log{entry.id}")
        if order is None:
            return
        entry.order_id, entry.order_status = order.id, order.status.value
        if order.reject_reason and order.filled_qty == 0 and not order.status.is_open:
            return
        if signal.side is Side.SELL:
            self.risk.on_exit()
        else:
            if self.ledger.qty <= 0:
                self.ledger.entries = 0
            self.ledger.entries += 1
        self._seen[order.id] = _Seen()
        self._track(order, entry)

    # ---- fills -> ledger -----------------------------------------------------------------------
    async def sync_orders(self) -> None:
        for order_id, entry in list(self._open.items()):
            order = await self.exchange.get_order(self.symbol, order_id)
            self._track(order, entry)

    def _track(self, order: Order, entry: LogEntry) -> None:
        """Apply new fills of `order` and keep watching it while it is open."""
        self._apply_order_delta(order, entry)
        if order.status.is_open:
            self._open[order.id] = entry
            return
        self._open.pop(order.id, None)
        self._seen.pop(order.id, None)
        if order.side is Side.SELL and entry.pnl is not None:
            self.ledger.exits.append(entry.pnl)

    def _apply_order_delta(self, order: Order, entry: LogEntry) -> None:
        seen = self._seen.setdefault(order.id, _Seen())
        d_qty = order.filled_qty - seen.filled_qty
        d_quote = order.quote_filled - seen.quote_filled
        d_fee = order.fee - seen.fee
        seen.filled_qty, seen.quote_filled, seen.fee = order.filled_qty, order.quote_filled, order.fee
        entry.order_status = order.status.value
        entry.filled_qty, entry.avg_price = order.filled_qty, order.avg_price
        entry.fee, entry.fee_asset = order.fee, order.fee_asset
        if d_qty <= 0:
            return
        led = self.ledger
        if order.side is Side.BUY:
            led.qty += d_qty - d_fee  # fee is taken in base on buys
            led.cost += d_quote
        else:
            proceeds = d_quote - d_fee  # fee is taken in quote on sells
            removed_cost = led.cost * d_qty / led.qty if led.qty > 0 else ZERO
            pnl = proceeds - removed_cost
            led.qty -= d_qty
            led.cost -= removed_cost
            led.realized += pnl
            entry.pnl = (entry.pnl or ZERO) + pnl
            if removed_cost > 0:
                entry.pnl_pct = entry.pnl / removed_cost * 100 if entry.pnl_pct is None else entry.pnl_pct
            if led.qty < self.market.min_qty:  # unsellable dust counts as flat
                led.qty, led.cost, led.entries = ZERO, ZERO, 0

    # ---- kill switch ---------------------------------------------------------------------------
    async def kill(self) -> list[Order]:
        """Stop trading and cancel every open order. Never raises: it must always finish."""
        self.risk.kill()
        self.stopped = True
        try:
            canceled = await self.exchange.cancel_all(self.symbol)
        except Exception:
            canceled = []
        with contextlib.suppress(Exception):
            await self.sync_orders()
        return canceled

    # ---- snapshots -----------------------------------------------------------------------------
    async def snapshot(self) -> dict[str, Any]:
        price = self.last_price or ZERO
        view = await self.view(self.equity_curve[-1].ts if self.equity_curve else utcnow(), price)
        open_orders = await self.exchange.get_open_orders(self.symbol)
        start = self.equity_curve[0].equity if self.equity_curve else view.equity
        unrealized = (view.position_qty * price - self.ledger.cost) if view.position_qty > 0 else ZERO
        return {
            "symbol": self.symbol,
            "resolution": self.resolution,
            "strategy": self.strategy.describe(),
            "price": str(price),
            "equity": str(view.equity),
            "start_equity": str(start),
            "pnl": str(view.equity - start),
            "pnl_pct": str((view.equity / start - 1) * 100) if start > 0 else "0",
            "realized_pnl": str(self.ledger.realized),
            "unrealized_pnl": str(unrealized),
            "position_qty": str(view.position_qty),
            "avg_entry": str(view.avg_entry) if view.avg_entry is not None else None,
            "quote_free": str(view.quote_free),
            "halted": self.risk.halted,
            "halt_reason": self.risk.halt_reason,
            "killed": self.risk.killed,
            "stopped": self.stopped,
            "open_orders": [o.to_dict() for o in open_orders],
            "candles_seen": len(self.equity_curve),
        }
