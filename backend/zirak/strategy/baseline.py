"""The four baseline strategies: EMA crossover, RSI mean reversion, grid, DCA.

They are intentionally simple and transparent. Stop-loss / take-profit / sizing limits live in the
RiskManager, not here, so every strategy gets the same protection.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from zirak.i18n import fa_num, fa_pct
from zirak.indicators import ema, last, rsi
from zirak.models import HUNDRED, Side
from zirak.strategy.base import Signal, Strategy, StrategyContext


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


class EmaCross(Strategy):
    key = "ema_cross"
    title_fa = "روند با تقاطع میانگین‌ها"
    description_fa = "وقتی میانگین متحرک کوتاه از بلند بالاتر برود می‌خرد و با برگشت آن می‌فروشد."

    def __init__(self, fast: int = 12, slow: int = 26, size_pct: float = 50, **kw: Any) -> None:
        super().__init__(fast=fast, slow=slow, size_pct=size_pct, **kw)
        self.fast, self.slow, self.size_pct = int(fast), int(slow), _d(size_pct)
        self.warmup = self.slow + 2

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        if len(ctx.df) < self.warmup:
            return []
        close = ctx.df["close"]
        f, s = ema(close, self.fast), ema(close, self.slow)
        f_now, s_now, f_prev, s_prev = last(f), last(s), last(f.iloc[:-1]), last(s.iloc[:-1])
        if None in (f_now, s_now, f_prev, s_prev):
            return []
        assert f_now is not None and s_now is not None and f_prev is not None and s_prev is not None
        ind = {f"ema{self.fast}": f_now, f"ema{self.slow}": s_now, "close": ctx.close}
        if f_prev <= s_prev and f_now > s_now and not ctx.in_position:
            return [
                Signal(
                    Side.BUY,
                    self.size_pct,
                    "ema_cross_up",
                    f"میانگین {fa_num(self.fast, 0)} از میانگین {fa_num(self.slow, 0)} بالاتر رفت؛ "
                    "نشانهٔ شروع روند صعودی.",
                    ind,
                )
            ]
        if f_prev >= s_prev and f_now < s_now and ctx.in_position:
            return [
                Signal(
                    Side.SELL,
                    HUNDRED,
                    "ema_cross_down",
                    f"میانگین {fa_num(self.fast, 0)} زیر میانگین {fa_num(self.slow, 0)} رفت؛ "
                    "روند ضعیف شده و از معامله خارج می‌شویم.",
                    ind,
                )
            ]
        return []


class RsiReversion(Strategy):
    key = "rsi_reversion"
    title_fa = "بازگشت به میانگین با RSI"
    description_fa = "وقتی بازار بیش‌فروش شود (RSI پایین) می‌خرد و در بیش‌خرید می‌فروشد."

    def __init__(
        self, period: int = 14, low: float = 30, high: float = 65, size_pct: float = 40, **kw: Any
    ) -> None:
        super().__init__(period=period, low=low, high=high, size_pct=size_pct, **kw)
        self.period, self.low, self.high, self.size_pct = int(period), float(low), float(high), _d(size_pct)
        self.warmup = self.period + 2

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        if len(ctx.df) < self.warmup:
            return []
        value = last(rsi(ctx.df["close"], self.period))
        if value is None:
            return []
        ind = {f"rsi{self.period}": value, "close": ctx.close}
        if value < self.low and not ctx.in_position:
            return [
                Signal(
                    Side.BUY,
                    self.size_pct,
                    "rsi_oversold",
                    f"RSI به {fa_num(value, 1)} رسید (زیر {fa_num(self.low, 0)})؛ بازار بیش‌فروش است.",
                    ind,
                )
            ]
        if value > self.high and ctx.in_position:
            return [
                Signal(
                    Side.SELL,
                    HUNDRED,
                    "rsi_overbought",
                    f"RSI به {fa_num(value, 1)} رسید (بالای {fa_num(self.high, 0)})؛ سود را برمی‌داریم.",
                    ind,
                )
            ]
        return []


class Grid(Strategy):
    """A transparent grid on closes: buy one slice each time price closes below a lower level, sell one
    slice each time it closes above the next level up. Range auto-centres on the first candle when
    `lower`/`upper` are not given."""

    key = "grid"
    title_fa = "گرید (خرید پله‌ای در نوسان)"
    description_fa = "بازه‌ای قیمت را پله‌بندی می‌کند؛ در هر پلهٔ پایین می‌خرد و در پلهٔ بالاتر می‌فروشد."

    def __init__(
        self,
        levels: int = 8,
        range_pct: float = 8,
        lower: float | None = None,
        upper: float | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(levels=levels, range_pct=range_pct, lower=lower, upper=upper, **kw)
        self.n = max(2, int(levels))
        self.range_pct = float(range_pct)
        self.lower, self.upper = lower, upper
        self.grid: list[float] = []
        self.last_level: int | None = None
        self.held = 0  # slices currently held
        self.warmup = 1

    def _level(self, price: float) -> int:
        """Index of the grid band the price is in (0 = below the lowest line)."""
        return sum(1 for g in self.grid if price >= g)

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        price = ctx.close
        if not self.grid:
            lo = self.lower or price * (1 - self.range_pct / 200)
            hi = self.upper or price * (1 + self.range_pct / 200)
            step = (hi - lo) / self.n
            self.grid = [lo + step * i for i in range(self.n + 1)]
            self.last_level = self._level(price)
            return []
        if not ctx.in_position:
            self.held = 0
        level = self._level(price)
        prev = self.last_level if self.last_level is not None else level
        self.last_level = level
        ind = {
            "close": price,
            "grid_level": float(level),
            "grid_low": self.grid[0],
            "grid_high": self.grid[-1],
        }
        slice_pct = _d(100 / self.n)
        if level < prev and level > 0:
            self.held += 1
            return [
                Signal(
                    Side.BUY,
                    slice_pct,
                    "grid_buy",
                    f"قیمت به پلهٔ {fa_num(level, 0)} از {fa_num(self.n, 0)} پایین آمد؛ یک سهم "
                    f"({fa_pct(float(slice_pct))} سرمایه) می‌خریم.",
                    ind,
                )
            ]
        if level > prev and ctx.in_position and self.held > 0:
            pct = _d(100 / self.held)
            self.held -= 1
            return [
                Signal(
                    Side.SELL,
                    pct,
                    "grid_sell",
                    f"قیمت به پلهٔ {fa_num(level, 0)} بالا رفت؛ یک سهم را با سود می‌فروشیم.",
                    ind,
                )
            ]
        return []


class Dca(Strategy):
    key = "dca"
    title_fa = "خرید دوره‌ای (DCA)"
    description_fa = "هر چند کندل یک مقدار ثابت می‌خرد و وقتی کل سبد به سود هدف رسید می‌فروشد."

    def __init__(
        self,
        every: int = 24,
        size_pct: float = 5,
        take_profit_pct: float = 6,
        max_entries: int = 10,
        **kw: Any,
    ) -> None:
        super().__init__(
            every=every, size_pct=size_pct, take_profit_pct=take_profit_pct, max_entries=max_entries, **kw
        )
        self.every, self.size_pct = max(1, int(every)), _d(size_pct)
        self.tp, self.max_entries = float(take_profit_pct), int(max_entries)
        self.count = 0

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        self.count += 1
        ind = {"close": ctx.close, "entries": float(ctx.entries)}
        if ctx.in_position and ctx.avg_entry is not None:
            gain = (ctx.close / float(ctx.avg_entry) - 1) * 100
            ind["gain_pct"] = gain
            if gain >= self.tp:
                return [
                    Signal(
                        Side.SELL,
                        HUNDRED,
                        "dca_take_profit",
                        f"سبد خریدهای دوره‌ای {fa_pct(gain)} در سود است؛ همه را می‌فروشیم.",
                        ind,
                    )
                ]
        if self.count % self.every == 1 % self.every and ctx.entries < self.max_entries:
            return [
                Signal(
                    Side.BUY,
                    self.size_pct,
                    "dca_buy",
                    f"نوبت خرید دوره‌ای است ({fa_num(ctx.entries + 1, 0)} از {fa_num(self.max_entries, 0)})؛ "
                    f"{fa_pct(float(self.size_pct))} سرمایه می‌خریم.",
                    ind,
                )
            ]
        return []
