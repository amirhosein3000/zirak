"""RiskManager: the deterministic gate between a strategy's ideas and real orders.

It sizes every buy, enforces max exposure, the per-order cap, stop-loss / take-profit, the daily loss
limit (halts new buys for the rest of the UTC day, optionally flattening), cooldown after exits, and the
market's precision / minimum order size. Sells that reduce risk are allowed even while halted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from zirak.i18n import fa_num, fa_pct
from zirak.models import HUNDRED, ONE, ZERO, Market, Side
from zirak.strategy.base import Signal


def _opt(x: Any) -> Decimal | None:
    return None if x is None else Decimal(str(x))


@dataclass
class RiskConfig:
    max_position_pct: Decimal = Decimal("80")  # max value of the position as % of equity
    max_order_quote: Decimal | None = None  # per-order cap in quote currency
    stop_loss_pct: Decimal | None = Decimal("5")
    take_profit_pct: Decimal | None = None
    daily_loss_limit_pct: Decimal | None = Decimal("5")
    cooldown_candles: int = 0  # no new buys for N candles after any exit
    flatten_on_halt: bool = True  # sell everything when the daily loss limit trips

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RiskConfig:
        cfg = cls()
        for key in (
            "max_position_pct",
            "max_order_quote",
            "stop_loss_pct",
            "take_profit_pct",
            "daily_loss_limit_pct",
        ):
            if key in d:
                setattr(cfg, key, _opt(d[key]))
        if "cooldown_candles" in d:
            cfg.cooldown_candles = int(d["cooldown_candles"])
        if "flatten_on_halt" in d:
            cfg.flatten_on_halt = bool(d["flatten_on_halt"])
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class PortfolioView:
    now: datetime
    price: Decimal
    position_qty: Decimal  # base held by this bot
    avg_entry: Decimal | None  # quote paid per unit of base held, fees included
    equity: Decimal  # quote + base * price
    quote_free: Decimal
    base_free: Decimal


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    qty: Decimal
    code: str  # "ok" or a rejection code
    notes_fa: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "qty": str(self.qty), "code": self.code, "notes_fa": self.notes_fa}


class RiskManager:
    def __init__(self, config: RiskConfig, market: Market, cost_buffer: Decimal = Decimal("0.02")) -> None:
        self.cfg = config
        self.market = market
        #: fraction of free quote kept back for fees/slippage when sizing buys
        self.cost_buffer = cost_buffer
        self.day: date | None = None
        self.day_start_equity: Decimal | None = None
        self.halted = False
        self.halt_reason = ""
        self.killed = False
        self.candle_index = 0
        self.cooldown_until = -1

    # ---- lifecycle -------------------------------------------------------------------------
    def kill(self, reason: str = "kill_switch") -> None:
        self.killed = True
        self.halted = True
        self.halt_reason = reason

    def on_candle(self, view: PortfolioView) -> list[Signal]:
        """Advance one candle: roll the trading day and enforce the daily loss limit."""
        self.candle_index += 1
        today = view.now.date()
        if today != self.day:
            self.day = today
            self.day_start_equity = view.equity
            if not self.killed:
                self.halted, self.halt_reason = False, ""
        limit = self.cfg.daily_loss_limit_pct
        if self.halted or limit is None or not self.day_start_equity:
            return []
        loss_pct = (self.day_start_equity - view.equity) / self.day_start_equity * HUNDRED
        if loss_pct >= limit:
            self.halted, self.halt_reason = True, "daily_loss_limit"
            if self.cfg.flatten_on_halt and view.position_qty > 0:
                return [
                    Signal(
                        Side.SELL,
                        HUNDRED,
                        "daily_loss_limit",
                        f"زیان امروز به {fa_pct(loss_pct)} رسید (سقف {fa_pct(limit)})؛ معاملات امروز "
                        "متوقف و موقعیت بسته می‌شود.",
                        {"daily_loss_pct": float(loss_pct)},
                    )
                ]
        return []

    def exit_signals(self, view: PortfolioView) -> list[Signal]:
        """Stop-loss / take-profit on the whole position, measured from the average entry price."""
        if view.position_qty < self.market.min_qty or view.avg_entry is None or view.avg_entry <= 0:
            return []  # flat, or only unsellable dust left
        change = (view.price / view.avg_entry - ONE) * HUNDRED
        ind = {
            "change_from_entry_pct": float(change),
            "avg_entry": float(view.avg_entry),
            "close": float(view.price),
        }
        sl, tp = self.cfg.stop_loss_pct, self.cfg.take_profit_pct
        if sl is not None and change <= -sl:
            return [
                Signal(
                    Side.SELL,
                    HUNDRED,
                    "stop_loss",
                    f"قیمت {fa_pct(-change)} زیر میانگین خرید رفت و به حد ضرر {fa_pct(sl)} رسید؛ "
                    "برای جلوگیری از زیان بیشتر می‌فروشیم.",
                    ind,
                )
            ]
        if tp is not None and change >= tp:
            return [
                Signal(
                    Side.SELL,
                    HUNDRED,
                    "take_profit",
                    f"قیمت {fa_pct(change)} بالاتر از میانگین خرید است و به حد سود {fa_pct(tp)} رسید.",
                    ind,
                )
            ]
        return []

    def on_exit(self) -> None:
        if self.cfg.cooldown_candles > 0:
            self.cooldown_until = self.candle_index + self.cfg.cooldown_candles

    # ---- the gate --------------------------------------------------------------------------
    def review(self, signal: Signal, view: PortfolioView) -> RiskDecision:
        if signal.side is Side.SELL:
            return self._review_sell(signal, view)
        return self._review_buy(signal, view)

    def _review_buy(self, signal: Signal, view: PortfolioView) -> RiskDecision:
        m = self.market
        if self.killed:
            return RiskDecision(False, ZERO, "killed", ["کلید توقف اضطراری فعال است."])
        if self.halted:
            return RiskDecision(
                False,
                ZERO,
                self.halt_reason or "halted",
                ["به سقف زیان روزانه رسیده‌ایم؛ تا فردا خرید جدید انجام نمی‌شود."],
            )
        if self.candle_index <= self.cooldown_until:
            return RiskDecision(False, ZERO, "cooldown", ["دورهٔ استراحت بعد از فروش هنوز تمام نشده است."])
        if view.price <= 0 or view.equity <= 0:
            return RiskDecision(False, ZERO, "no_equity", ["سرمایه‌ای برای خرید نیست."])
        notes: list[str] = []
        want = view.equity * signal.size_pct / HUNDRED
        position_value = view.position_qty * view.price
        room = view.equity * self.cfg.max_position_pct / HUNDRED - position_value
        if room <= 0:
            return RiskDecision(
                False,
                ZERO,
                "max_exposure",
                [f"سهم این دارایی از سرمایه به سقف {fa_pct(self.cfg.max_position_pct, 0)} رسیده است."],
            )
        quote = want
        if quote > room:
            quote = room
            notes.append(f"حجم خرید به سقف {fa_pct(self.cfg.max_position_pct, 0)} سرمایه محدود شد.")
        cap = self.cfg.max_order_quote
        if cap is not None and quote > cap:
            quote = cap
            notes.append(f"حجم به سقف هر سفارش ({fa_num(cap)} {m.quote}) محدود شد.")
        spendable = view.quote_free / (ONE + self.cost_buffer)
        if quote > spendable:
            quote = spendable
            notes.append("حجم به موجودی آزاد (پس از کسر کارمزد و لغزش) محدود شد.")
        qty = m.round_qty(quote / view.price)
        problem = m.check_order(qty, view.price) if qty > 0 else "qty_not_positive"
        if problem:
            return RiskDecision(False, ZERO, problem, [*notes, "مبلغ سفارش از حداقل مجاز بازار کمتر است."])
        return RiskDecision(True, qty, "ok", notes)

    def _review_sell(self, signal: Signal, view: PortfolioView) -> RiskDecision:
        m = self.market
        held = min(view.position_qty, view.base_free)
        if held <= 0:
            return RiskDecision(False, ZERO, "no_position", ["موقعیتی برای فروش نیست."])
        qty = m.round_qty(held * signal.size_pct / HUNDRED)
        if held - qty < m.min_qty or (held - qty) * view.price < m.min_notional:
            qty = m.round_qty(held)  # do not leave unsellable dust behind
        problem = m.check_order(qty, view.price) if qty > 0 else "qty_not_positive"
        if problem:
            return RiskDecision(False, ZERO, problem, ["مقدار باقی‌مانده کمتر از حداقل سفارش بازار است."])
        return RiskDecision(True, qty, "ok", [])
