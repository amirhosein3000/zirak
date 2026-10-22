"""The trading agent: many markets, one account, one code path for backtest, shadow and live.

Per closed bar (`on_bar`):
  1. sync orders -> positions (fills, take-profits, exits)
  2. value the account in Toman; account guard: daily loss, drawdown from peak, distance to the credit
     plan's liquidation limit, challenge clock  ->  ok | pause (no entries) | flatten (+ kill)
  3. refresh the posture (LLM agent or rules) when due
  4. manage positions: stop-loss, time stop, guard-driven flatten
  5. if allowed: scan setups -> ML meta-labeler (p, EV, Kelly) -> posture -> risk sizing -> order
  6. journal every decision and the equity point

Between bars (`on_tick`, live and shadow only): fills, intra-bar stops from the best bid, stale maker
entries, the end-of-challenge flatten.

Hard limits live here and in the exchange guard; neither the ML model nor the LLM can bypass them.
"""

from __future__ import annotations

import math
import time as _time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from zirak.agent.config import AgentConfig
from zirak.agent.features import WARMUP_BARS, feature_frame, implied_closes, row_features
from zirak.agent.journal import Journal
from zirak.agent.labeling import Costs
from zirak.agent.model import MetaModel
from zirak.agent.posture import Posture, PostureAgent, rule_posture
from zirak.agent.setups import Candidate, scan
from zirak.config import Settings
from zirak.exchange.base import ExchangeClient
from zirak.exchange.guard import HardLimitExceeded, LiveTradingDisabled, check_hard_limits, require_live
from zirak.fees import apply_slippage
from zirak.i18n import fa_num, fa_pct
from zirak.models import (
    HUNDRED,
    ONE,
    ZERO,
    Candle,
    Market,
    Order,
    OrderRequest,
    OrderType,
    Side,
    resolution_delta,
)

BPS = Decimal(10000)


@dataclass
class Position:
    symbol: str
    setup: str
    decision_id: str
    qty: Decimal  # base held (net of fees)
    cost: Decimal  # Toman paid, fees included
    entry_price: Decimal
    stop: Decimal
    take_profit: Decimal
    opened_at: str
    max_bars: int
    bars: int = 0
    tp_order_id: str | None = None
    exit_order_id: str | None = None
    exit_reason: str = ""
    proceeds: Decimal = ZERO  # Toman received from partial exits so far (fees deducted)
    sold: Decimal = ZERO

    def to_dict(self) -> dict[str, Any]:
        return {k: (format(v, "f") if isinstance(v, Decimal) else v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Position:
        dec = {"qty", "cost", "entry_price", "stop", "take_profit", "proceeds", "sold"}
        kw: dict[str, Any] = {k: (Decimal(v) if k in dec else v) for k, v in d.items()}
        return cls(**kw)


@dataclass
class PendingEntry:
    symbol: str
    setup: str
    decision_id: str
    order_id: str
    placed_at: str
    tp_pct: float
    sl_pct: float
    max_bars: int
    bars_waited: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GuardState:
    peak: Decimal = ZERO
    day: str = ""
    day_start: Decimal = ZERO
    killed: bool = False
    kill_reason: str = ""
    last_status: str = "ok"
    cooldown_until: dict[str, int] = field(default_factory=dict)


Clock = Callable[[], datetime]


class Agent:
    def __init__(
        self,
        cfg: AgentConfig,
        exchange: ExchangeClient,
        markets: dict[str, Market],
        model: MetaModel,
        journal: Journal,
        costs: Costs,
        clock: Clock,
        settings: Settings | None = None,
        posture_agent: PostureAgent | None = None,
        recorded_postures: list[Posture] | None = None,
        trainer: Callable[[datetime], Awaitable[MetaModel | None]] | None = None,
        package: dict[str, Any] | None = None,
    ) -> None:
        self.cfg = cfg
        self.ex = exchange
        self.markets = markets
        self.model = model
        self.journal = journal
        self.costs = costs
        self.clock = clock
        self.settings = settings
        self.posture_agent = posture_agent
        self.recorded = sorted(recorded_postures or [], key=lambda p: p.ts)
        self.trainer = trainer
        self.package = package  # credit plan limits (live): start_balance, liquidity_limit, ...
        self.step = resolution_delta(cfg.resolution)
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, PendingEntry] = {}
        self.guard = GuardState()
        self.posture: Posture | None = None
        self.bar_index = 0
        self.last_price: dict[str, Decimal] = {}
        self.frames: dict[str, pd.DataFrame] = {}
        self.candles: dict[str, list[Candle]] = {}
        self.last_train: datetime | None = None
        self.errors = 0
        self.stopped = False
        self.equity_now = ZERO
        self._sell_seen: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
        #: backtests pass whole-series feature frames (identical, much faster); live builds a rolling window
        self.precomputed: dict[str, pd.DataFrame] | None = None

    # ---- helpers -----------------------------------------------------------------------------------
    @property
    def is_real(self) -> bool:
        return self.ex.is_real

    def _base(self, symbol: str) -> str:
        return self.markets[symbol].base

    def cost_pct(self) -> float:
        """Round-trip cost used in EV maths: maker-first entry assumes a maker fill half of the time."""
        c = self.costs
        entry = (c.maker + c.taker) / 2 if self.cfg.execution.entry == "maker_first" else c.taker + c.slippage
        exit_ = (
            c.maker + c.taker + c.slippage
        ) / 2  # take-profit is a maker order; stops/time exits are taker
        return (entry + exit_) * 100

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "pending": {k: v.to_dict() for k, v in self.pending.items()},
            "guard": {
                "peak": format(self.guard.peak, "f"),
                "day": self.guard.day,
                "day_start": format(self.guard.day_start, "f"),
                "killed": self.guard.killed,
                "kill_reason": self.guard.kill_reason,
                "last_status": self.guard.last_status,
                "cooldown_until": self.guard.cooldown_until,
            },
            "bar_index": self.bar_index,
            "posture": self.posture.to_dict() if self.posture else None,
            "model_id": self.model.card.model_id,
            "errors": self.errors,
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.positions = {k: Position.from_dict(v) for k, v in state.get("positions", {}).items()}
        self.pending = {k: PendingEntry(**v) for k, v in state.get("pending", {}).items()}
        g = state.get("guard", {})
        self.guard = GuardState(
            Decimal(g.get("peak", "0")),
            g.get("day", ""),
            Decimal(g.get("day_start", "0")),
            bool(g.get("killed", False)),
            g.get("kill_reason", ""),
            g.get("last_status", "ok"),
            dict(g.get("cooldown_until", {})),
        )
        self.bar_index = int(state.get("bar_index", 0))
        if state.get("posture"):
            self.posture = Posture.from_dict(state["posture"])

    def save_model(self) -> None:
        """Keep every model the run used (by id) so `zirak agent verify` can recompute its verdicts."""
        target = self.journal.dir / "models" / self.model.card.model_id
        if not target.exists():
            self.model.save(target)

    def _save(self) -> None:
        self.journal.save_state(self.snapshot_state())

    # ---- valuation & guard ---------------------------------------------------------------------------
    async def account(self) -> tuple[Decimal, Decimal, Decimal]:
        """(equity, free Toman, value of open positions) in Toman."""
        bal = await self.ex.get_balances()
        cash = bal["TMN"].total if "TMN" in bal else ZERO
        free = bal["TMN"].free if "TMN" in bal else ZERO
        held = ZERO
        for asset, b in bal.items():
            if asset == "TMN" or b.total <= 0:
                continue
            px = self.last_price.get(f"{asset}TMN")
            if px is not None:
                held += b.total * px
        return cash + held, free, held

    def check_guard(self, now: datetime, equity: Decimal) -> str:
        r, g = self.cfg.risk, self.guard
        day = now.date().isoformat()
        if day != g.day:
            g.day, g.day_start = day, equity
        g.peak = max(g.peak, equity)
        if g.killed:
            return f"killed:{g.kill_reason}"
        dd = (g.peak - equity) / g.peak * HUNDRED if g.peak > 0 else ZERO
        if dd >= Decimal(str(r.dd_kill_pct)):
            return f"kill:drawdown {dd:.2f}%"
        if self.package and self.package.get("liquidity_limit") and self.package.get("start_balance"):
            liq, start = Decimal(self.package["liquidity_limit"]), Decimal(self.package["start_balance"])
            cushion = start - liq
            if cushion > 0:
                left = (equity - liq) / cushion
                if left <= Decimal(str(r.liquidation_kill_cushion)):
                    return f"kill:liquidation cushion {left:.2f}"
                if left <= Decimal(str(r.liquidation_pause_cushion)):
                    return f"pause:liquidation cushion {left:.2f}"
        clk = self.cfg.clock
        if clk.end is not None:
            left_min = (clk.end - now).total_seconds() / 60
            if left_min <= clk.hard_flatten_before_end_min:
                return "flatten_hard:challenge end"
            if left_min <= clk.flatten_before_end_min:
                return "flatten:challenge end"
            if left_min <= clk.no_entry_before_end_h * 60:
                return "pause:challenge end near"
        if clk.start is not None and now < clk.start:
            return "pause:challenge not started"
        if dd >= Decimal(str(r.dd_pause_pct)):
            return f"pause:drawdown {dd:.2f}%"
        if g.day_start > 0:
            loss = (g.day_start - equity) / g.day_start * HUNDRED
            if loss >= Decimal(str(r.daily_loss_pct)):
                return f"pause:daily loss {loss:.2f}%"
        return "ok"

    # ---- orders ----------------------------------------------------------------------------------
    async def _place(
        self, symbol: str, side: Side, qty: Decimal, price: Decimal | None, tag: str
    ) -> Order | None:
        """Paper: as given. Real: guarded, LIMIT only (market -> marketable limit), capped, timed."""
        m = self.markets[symbol]
        otype = OrderType.LIMIT if price is not None else OrderType.MARKET
        req = OrderRequest(symbol, side, otype, qty, price, tag)
        try:
            if self.is_real:
                assert self.settings is not None
                require_live(self.settings)
                if req.price is None:
                    book = await self.ex.get_order_book(symbol)
                    touch = book.best_bid if side is Side.SELL else book.best_ask
                    ref = touch or self.last_price[symbol]
                    worst = apply_slippage(ref, side, Decimal(str(self.cfg.execution.max_slippage_bps)), m)
                    req = OrderRequest(symbol, side, OrderType.LIMIT, qty, worst, tag)
                assert req.price is not None
                check_hard_limits(self.settings, m, req, req.price)
            t0 = _time.perf_counter()
            order = await self.ex.place_order(req)
            ack_ms = (_time.perf_counter() - t0) * 1000
        except (LiveTradingDisabled, HardLimitExceeded) as e:
            self.errors += 1
            self.journal.order(
                {"ts": self.clock(), "symbol": symbol, "side": side.value, "error": str(e), "tag": tag}
            )
            return None
        except Exception as e:  # network / exchange error: never crash the loop on one order
            self.errors += 1
            self.journal.order(
                {"ts": self.clock(), "symbol": symbol, "side": side.value, "error": repr(e), "tag": tag}
            )
            return None
        self.journal.order(
            {
                "ts": self.clock(),
                "order_id": order.id,
                "symbol": symbol,
                "side": side.value,
                "type": req.type.value,
                "qty": req.qty,
                "price": req.price,
                "status": order.status.value,
                "reject_reason": order.reject_reason,
                "ack_ms": round(ack_ms, 2),
                "tag": tag,
            }
        )
        if order.status.value == "rejected":
            self.errors += 1
            return None
        return order

    async def _cancel(self, symbol: str, order_id: str) -> Order | None:
        try:
            return await self.ex.cancel_order(symbol, order_id)
        except Exception as e:
            self.errors += 1
            self.journal.order({"ts": self.clock(), "cancel": order_id, "error": repr(e)})
            return None

    async def _get(self, symbol: str, order_id: str) -> Order | None:
        try:
            return await self.ex.get_order(symbol, order_id)
        except Exception as e:
            self.errors += 1
            self.journal.order({"ts": self.clock(), "get": order_id, "error": repr(e)})
            return None

    # ---- order sync -> positions -----------------------------------------------------------------
    async def sync(self) -> None:
        now = self.clock()
        for sym, pe in list(self.pending.items()):
            o = await self._get(sym, pe.order_id)
            if o is None:
                continue
            if o.status.is_open:
                continue
            del self.pending[sym]
            if o.filled_qty <= 0:
                self.journal.decision(
                    {
                        "ts": now,
                        "kind": "entry_unfilled",
                        "symbol": sym,
                        "ref": pe.decision_id,
                        "reason_fa": "سفارش ورود (میکر) پر نشد و لغو شد.",
                    }
                )
                continue
            await self._open_position(pe, o)
        for sym, pos in list(self.positions.items()):
            for oid, kind in (
                (pos.tp_order_id, "take_profit"),
                (pos.exit_order_id, pos.exit_reason or "exit"),
            ):
                if not oid:
                    continue
                o = await self._get(sym, oid)
                if o is None:
                    continue
                self._apply_sell(pos, o, oid)
                if not o.status.is_open:
                    if oid == pos.tp_order_id:
                        pos.tp_order_id = None
                    else:
                        pos.exit_order_id = None
                    if pos.qty - pos.sold < self.markets[sym].min_qty:
                        self._close(pos, kind, now)
                        break
        self._save()

    def _apply_sell(self, pos: Position, o: Order, oid: str) -> None:
        seen = self._sell_seen.get(oid, (ZERO, ZERO, ZERO))
        d_qty, d_quote, d_fee = o.filled_qty - seen[0], o.quote_filled - seen[1], o.fee - seen[2]
        if d_qty <= 0:
            return
        self._sell_seen[oid] = (o.filled_qty, o.quote_filled, o.fee)
        proceeds = d_quote - (d_fee if o.fee_asset in ("TMN", "") else d_fee * (d_quote / d_qty))
        pos.sold += d_qty
        pos.proceeds += proceeds

    async def _open_position(self, pe: PendingEntry, o: Order) -> None:
        m = self.markets[pe.symbol]
        qty, cost = o.filled_qty, o.quote_filled
        if o.fee_asset == m.base:
            qty -= o.fee
        else:
            cost += o.fee
        qty = m.round_qty(qty)
        entry = o.avg_price or (cost / qty if qty > 0 else ZERO)
        tp = m.round_price(entry * (ONE + Decimal(str(pe.tp_pct)) / HUNDRED), Side.BUY)
        stop = m.round_price(entry * (ONE - Decimal(str(pe.sl_pct)) / HUNDRED), Side.SELL)
        pos = Position(
            pe.symbol,
            pe.setup,
            pe.decision_id,
            qty,
            cost,
            entry,
            stop,
            tp,
            self.clock().isoformat(),
            pe.max_bars,
        )
        self.positions[pe.symbol] = pos
        self.journal.decision(
            {
                "ts": self.clock(),
                "kind": "entry_filled",
                "symbol": pe.symbol,
                "ref": pe.decision_id,
                "qty": qty,
                "avg_price": entry,
                "cost_tmn": cost,
                "fee": o.fee,
                "fee_asset": o.fee_asset,
                "take_profit": tp,
                "stop": stop,
                "reason_fa": f"خرید پر شد؛ حد سود {fa_num(tp, 0)} و حد ضرر {fa_num(stop, 0)} تنظیم شد.",
            }
        )
        if qty >= m.min_qty and qty * tp >= m.min_notional:
            tpo = await self._place(pe.symbol, Side.SELL, qty, tp, f"tp:{pe.decision_id}")
            pos.tp_order_id = tpo.id if tpo else None

    def _close(self, pos: Position, kind: str, now: datetime) -> None:
        pnl = pos.proceeds - pos.cost * (pos.sold / pos.qty if pos.qty > 0 else ONE)
        pnl_pct = pnl / pos.cost * HUNDRED if pos.cost > 0 else ZERO
        self.positions.pop(pos.symbol, None)
        if kind in ("stop_loss", "kill", "flatten") or pnl < 0:
            self.guard.cooldown_until[pos.symbol] = self.bar_index + self.cfg.risk.cooldown_bars
        rec = {
            "ts": now,
            "kind": "exit",
            "symbol": pos.symbol,
            "ref": pos.decision_id,
            "exit": kind,
            "setup": pos.setup,
            "qty": pos.sold,
            "proceeds_tmn": pos.proceeds,
            "cost_tmn": pos.cost,
            "pnl_tmn": pnl,
            "pnl_pct": pnl_pct,
            "bars": pos.bars,
            "reason_fa": f"{EXIT_FA.get(kind, kind)}؛ نتیجه {fa_pct(pnl_pct, 2)} ({fa_num(pnl, 0)} تومان).",
        }
        self.journal.decision(rec)
        self.journal.trade(
            {
                "symbol": pos.symbol,
                "setup": pos.setup,
                "decision_id": pos.decision_id,
                "opened_at": pos.opened_at,
                "closed_at": now,
                "entry_price": pos.entry_price,
                "qty": pos.sold,
                "cost_tmn": pos.cost,
                "proceeds_tmn": pos.proceeds,
                "pnl_tmn": pnl,
                "pnl_pct": pnl_pct,
                "exit": kind,
                "bars": pos.bars,
            }
        )

    async def exit_position(self, pos: Position, reason: str, now: datetime) -> None:
        """Cancel the take-profit and sell what's left at market (real: marketable limit, in capped chunks)."""
        if pos.exit_order_id:
            return
        if pos.tp_order_id:
            o = await self._cancel(pos.symbol, pos.tp_order_id)
            if o is not None:
                self._apply_sell(pos, o, pos.tp_order_id)
            pos.tp_order_id = None
        m = self.markets[pos.symbol]
        left = m.round_qty(pos.qty - pos.sold)
        bal = await self.ex.get_balances()
        b = bal.get(m.base)
        if b is not None:
            left = min(left, m.round_qty(b.free))
        if left < m.min_qty or left * self.last_price.get(pos.symbol, pos.entry_price) < m.min_notional:
            self._close(pos, reason, now)  # dust: nothing sellable left
            return
        if self.is_real and self.settings is not None:
            cap = self.settings.max_order_for_quote("TMN")
            px = self.last_price.get(pos.symbol, pos.entry_price)
            if cap is not None and left * px > cap:
                left = m.round_qty(
                    cap / (px * (ONE + Decimal(str(self.cfg.execution.max_slippage_bps)) / BPS))
                )
        pos.exit_reason = reason
        o = await self._place(pos.symbol, Side.SELL, left, None, f"{reason}:{pos.decision_id}")
        pos.exit_order_id = o.id if o else None
        self.journal.decision(
            {
                "ts": now,
                "kind": "exit_order",
                "symbol": pos.symbol,
                "ref": pos.decision_id,
                "exit": reason,
                "qty": left,
                "reason_fa": EXIT_FA.get(reason, reason),
            }
        )

    # ---- posture -----------------------------------------------------------------------------------
    async def refresh_posture(self, now: datetime) -> None:
        if self.posture is not None:
            age = now - datetime.fromisoformat(self.posture.ts)
            if age < timedelta(minutes=self.cfg.posture_interval_min):
                return
        frames = {s: self.frames[s] for s in self.cfg.markets if s in self.frames}
        if self.recorded:
            chosen = [p for p in self.recorded if datetime.fromisoformat(p.ts) <= now]
            self.posture = chosen[-1] if chosen else rule_posture(now, frames)
        elif self.posture_agent is not None:
            self.posture = await self.posture_agent.decide(now, frames)
        else:
            self.posture = rule_posture(now, frames)
        self.journal.posture(self.posture.to_dict())

    # ---- the bar step ------------------------------------------------------------------------------
    async def on_bar(self, now: datetime, candles: dict[str, list[Candle]]) -> None:
        """`candles`: closed candles per market (traded + context), oldest first, ending at the bar that just closed."""
        if self.stopped:
            return
        self.bar_index += 1
        self.candles = candles
        for sym in self.cfg.markets:
            c = candles.get(sym)
            if c:
                self.last_price[sym] = c[-1].close
                if self.precomputed is not None and sym in self.precomputed:
                    self.frames[sym] = self.precomputed[sym].iloc[: len(c)]
                else:
                    self.frames[sym] = feature_frame(c[-(WARMUP_BARS + 200) :], implied_closes(candles, sym))
        if self.trainer is not None and (
            self.last_train is None or now - self.last_train >= timedelta(hours=self.cfg.model.retrain_hours)
        ):
            fresh = await self.trainer(now)
            if fresh is not None:
                self.model = fresh
                self.save_model()
                self.journal.decision(
                    {
                        "ts": now,
                        "kind": "model",
                        "model": fresh.card.to_dict(),
                        "reason_fa": "مدل یادگیری ماشین با داده‌های تا این لحظه دوباره آموزش دید.",
                    }
                )
            self.last_train = now
        await self.sync()
        equity, free, held = await self.account()
        self.equity_now = equity
        status = self.check_guard(now, equity)
        if status != self.guard.last_status:
            self.journal.decision(
                {
                    "ts": now,
                    "kind": "guard",
                    "status": status,
                    "equity_tmn": equity,
                    "reason_fa": GUARD_FA.get(status.split(":")[0], status),
                }
            )
            self.guard.last_status = status
        await self.refresh_posture(now)

        # positions: count bars, stops, time stops, flatten
        flatten = status.startswith(("kill", "flatten", "killed"))
        for sym, pos in list(self.positions.items()):
            if pos.exit_order_id:
                continue
            pos.bars += 1
            last = candles[sym][-1] if candles.get(sym) else None
            if flatten:
                await self.exit_position(pos, "flatten" if status.startswith("flatten") else "kill", now)
            elif last is not None and last.low <= pos.stop:
                await self.exit_position(pos, "stop_loss", now)
            elif pos.bars >= pos.max_bars:
                await self.exit_position(pos, "time_stop", now)
        if status.startswith("kill") and not self.guard.killed:
            self.guard.killed, self.guard.kill_reason = True, status.split(":", 1)[1]
            for sym, pe in list(self.pending.items()):
                await self._cancel(sym, pe.order_id)

        # stale maker entries (bar-driven runs: an entry limit lives for one bar)
        for sym, pe in list(self.pending.items()):
            pe.bars_waited += 1
            if pe.bars_waited >= 1 or flatten:
                await self._cancel(sym, pe.order_id)
        await self.sync()

        if status == "ok":
            await self.enter(now, equity, free, held)
        exposure = float(held / equity * HUNDRED) if equity > 0 else 0.0
        dd = float((self.guard.peak - equity) / self.guard.peak * HUNDRED) if self.guard.peak > 0 else 0.0
        self.journal.equity(now, equity, free, exposure, dd)
        self._save()

    async def enter(self, now: datetime, equity: Decimal, free: Decimal, held: Decimal) -> None:
        r = self.cfg.risk
        cost = self.cost_pct()
        min_tp = max(2.5 * cost, 0.5)
        found: list[tuple[float, Candidate, Any, Any]] = []
        for sym in self.cfg.markets:
            df = self.frames.get(sym)
            if df is None or len(df) < WARMUP_BARS or sym in self.positions or sym in self.pending:
                continue
            if self.guard.cooldown_until.get(sym, -1) >= self.bar_index:
                continue
            mp = self.posture.for_market(sym) if self.posture else None
            for cand in scan(df, len(df) - 1, sym, min_tp, enabled=tuple(self.cfg.setups)):
                feats = row_features(df, len(df) - 1)
                v = self.model.decide(feats, cand.setup, cand.tp_pct, cand.sl_pct, cost)
                allowed = mp is None or mp.allows(cand.setup)
                rec: dict[str, Any] = {
                    "ts": now,
                    "kind": "candidate",
                    "symbol": sym,
                    "setup": cand.setup,
                    "price": cand.price,
                    "tp_pct": cand.tp_pct,
                    "sl_pct": cand.sl_pct,
                    "max_bars": cand.max_bars,
                    "indicators": cand.indicators,
                    "features": {k: (None if math.isnan(x) else x) for k, x in feats.items()},
                    "signal_fa": cand.reason_fa,
                    "model": {
                        "id": self.model.card.model_id,
                        "source": v.source,
                        "prob": v.prob,
                        "ev_pct": v.ev_pct,
                        "kelly": v.kelly,
                        "size_mult": v.size_mult,
                        "why": v.why,
                        "cost_pct": cost,
                    },
                    "posture": {
                        "stance": mp.stance,
                        "mult": mp.risk_multiplier,
                        "source": self.posture.source,
                        "reason_fa": mp.reason_fa,
                    }
                    if mp and self.posture
                    else None,
                }
                if not v.take:
                    rec.update(
                        action="skip",
                        reason_fa=f"مدل هوش مصنوعی رد کرد: احتمال موفقیت {fa_pct(v.prob * 100, 0)}، "
                        f"ارزش مورد انتظار {fa_pct(v.ev_pct, 2)} بعد از کارمزد.",
                    )
                    self.journal.decision(rec)
                    continue
                if not allowed:
                    rec.update(
                        action="skip",
                        reason_fa=f"عامل هوشمند این الگو را در این بازار فعلاً مجاز نمی‌داند: {mp.reason_fa if mp else ''}",
                    )
                    self.journal.decision(rec)
                    continue
                found.append((v.ev_pct, cand, v, rec))
        found.sort(key=lambda t: -t[0])
        open_n = len(self.positions) + len(self.pending)
        for _ev, cand, v, rec in found:
            sym = cand.symbol
            if sym in self.pending or sym in self.positions:
                rec.update(action="skip", reason_fa="برای این بازار در همین کندل ورود دیگری انتخاب شد.")
                self.journal.decision(rec)
                continue
            if open_n >= r.max_positions:
                rec.update(action="skip", reason_fa=f"سقف {fa_num(r.max_positions, 0)} موقعیت هم‌زمان پر است.")
                self.journal.decision(rec)
                continue
            mp = self.posture.for_market(sym) if self.posture else None
            mult = Decimal(str(v.size_mult)) * Decimal(str(mp.risk_multiplier if mp else 1.0))
            sized = self.size(sym, equity, free, held, cand, mult)
            rec["risk"] = sized
            if sized["qty"] == "0":
                rec.update(action="skip", reason_fa=sized["why_fa"])
                self.journal.decision(rec)
                continue
            m = self.markets[sym]
            qty = Decimal(sized["qty"])
            price: Decimal | None = None
            if self.cfg.execution.entry == "maker_first":
                ref = self.last_price[sym]
                price = m.round_price(
                    ref * (ONE - Decimal(str(self.cfg.execution.maker_offset_bps)) / BPS), Side.SELL
                )
            rec.update(
                action="buy",
                reason_fa=f"{cand.reason_fa} مدل: احتمال {fa_pct(v.prob * 100, 0)}، ارزش مورد انتظار "
                f"{fa_pct(v.ev_pct, 2)}؛ حجم {fa_num(Decimal(sized['value_tmn']), 0)} تومان.",
            )
            did = self.journal.decision(rec)
            order = await self._place(sym, Side.BUY, qty, price, f"entry:{did}")
            if order is None:
                continue
            self.pending[sym] = PendingEntry(
                sym, cand.setup, did, order.id, now.isoformat(), cand.tp_pct, cand.sl_pct, cand.max_bars
            )
            open_n += 1
            held += Decimal(sized["value_tmn"])
            free -= Decimal(sized["value_tmn"])

    def size(
        self, sym: str, equity: Decimal, free: Decimal, held: Decimal, cand: Candidate, mult: Decimal
    ) -> dict[str, Any]:
        """Risk-based size, then every hard cap. Returns the numbers and which cap bound."""
        r, m = self.cfg.risk, self.markets[sym]
        px = self.last_price[sym]
        risk_amt = equity * Decimal(str(r.risk_per_trade_pct)) / HUNDRED * mult
        value = risk_amt / (Decimal(str(cand.sl_pct)) / HUNDRED)
        caps = {
            "risk_based": value,
            "max_position": equity * Decimal(str(r.max_position_pct)) / HUNDRED,
            "exposure_room": equity * Decimal(str(r.max_exposure_pct)) / HUNDRED - held,
            "free_cash": free
            * (ONE - Decimal(str(r.cash_buffer_pct)) / HUNDRED)
            / (ONE + Decimal(str(self.costs.taker))),
        }
        if self.is_real and self.settings is not None and self.settings.max_order_tmn:
            caps["max_order_tmn"] = self.settings.max_order_tmn
        bind = min(caps, key=lambda k: caps[k])
        value = max(caps[bind], ZERO)
        qty = m.round_qty(value / px) if px > 0 else ZERO
        problem = m.check_order(qty, px) if qty > 0 else "qty_not_positive"
        out = {
            "equity_tmn": format(equity.quantize(ONE), "f"),
            "risk_tmn": format(risk_amt.quantize(ONE), "f"),
            "multiplier": float(mult),
            "bound_by": bind,
            "value_tmn": format((qty * px).quantize(ONE), "f"),
            "qty": format(qty, "f") if not problem else "0",
        }
        if problem:
            out["why_fa"] = f"حجم پس از اعمال سقف‌ها ({bind}) از حداقل سفارش بازار کمتر شد."
        return out

    # ---- live / shadow ticks ------------------------------------------------------------------------
    async def on_tick(self, now: datetime) -> None:
        """Between bars: fills, intra-bar stops from the best bid, stale maker entries, the end flatten."""
        if self.stopped:
            return
        await self.sync()
        for sym, pos in list(self.positions.items()):
            if pos.exit_order_id:
                continue
            try:
                book = await self.ex.get_order_book(sym)
            except Exception:
                self.errors += 1
                continue
            bid = book.best_bid
            if bid is not None:
                self.last_price[sym] = bid
                if bid <= pos.stop:
                    await self.exit_position(pos, "stop_loss", now)
        wait = timedelta(seconds=self.cfg.execution.maker_wait_s)
        for sym, pe in list(self.pending.items()):
            if now - datetime.fromisoformat(pe.placed_at) >= wait:
                await self._cancel(sym, pe.order_id)
        clk = self.cfg.clock
        if clk.end is not None and (clk.end - now).total_seconds() / 60 <= clk.flatten_before_end_min:
            for pos in list(self.positions.values()):
                if not pos.exit_order_id:
                    await self.exit_position(pos, "flatten", now)
        self._save()


EXIT_FA = {
    "take_profit": "به حد سود رسید و فروخته شد",
    "stop_loss": "حد ضرر فعال شد و فروخته شد",
    "time_stop": "زمان مجاز موقعیت تمام شد و فروخته شد",
    "flatten": "نزدیک پایان چالش، همه‌چیز به تومان تبدیل شد",
    "kill": "کلید توقف/محافظ حساب فعال شد و موقعیت بسته شد",
    "exit": "موقعیت بسته شد",
}
GUARD_FA = {
    "ok": "شرایط حساب عادی است؛ ورود مجاز است.",
    "pause": "ورود جدید موقتاً متوقف شد (محافظ حساب).",
    "flatten": "زمان پایان چالش نزدیک است؛ موقعیت‌ها بسته می‌شوند.",
    "flatten_hard": "پایان چالش: فروش فوری همهٔ موقعیت‌ها به تومان.",
    "kill": "محافظ حساب: افت بیش از حد؛ همه‌چیز بسته و ربات متوقف شد.",
    "killed": "ربات متوقف است.",
}
