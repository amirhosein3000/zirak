"""BotRunner: runs one paper bot in the background (inside the API process or the CLI) and owns the
kill switch.

Kill switch = `kill()`: writes the KILL file, halts the RiskManager, cancels every open order and stops
the loop. The loop also polls the KILL file each step, so `zirak kill` from another terminal stops a
bot running in the API process even if the API, the LLM or the market-data feed is unresponsive.
"""

from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from typing import Any

import httpx

from zirak.backtest.engine import cost_buffer
from zirak.config import Settings
from zirak.engine.bot import Bot, SimClock
from zirak.engine.risk import RiskConfig, RiskManager
from zirak.exchange.base import ExchangeClient
from zirak.exchange.guard import live_blockers
from zirak.exchange.paper import PaperExchange
from zirak.exchange.replay import ReplayExchange
from zirak.exchange.wallex import WallexAPIError, WallexClient
from zirak.fees import FeeModel
from zirak.models import ZERO, Market, Order, OrderBook, resolution_delta, utcnow
from zirak.strategy.base import Strategy


class RunnerError(RuntimeError):
    pass


def book_is_sane(book: OrderBook) -> bool:
    """A usable snapshot has both sides and is not crossed (best bid below best ask)."""
    bid, ask = book.best_bid, book.best_ask
    return bid is not None and ask is not None and 0 < bid < ask


class BotRunner:
    def __init__(
        self, settings: Settings, replay: ReplayExchange, live: ExchangeClient | None = None
    ) -> None:
        self.settings = settings
        self.replay = replay
        #: public market-data client for DATA_SOURCE=wallex (paper trading on live data)
        self.live = live
        self.bot: Bot | None = None
        self.paper: PaperExchange | None = None
        self.task: asyncio.Task[None] | None = None
        self.mode = "paper-replay"
        self.speed_s = 1.0
        self.error: str | None = None
        self.started_at = utcnow()
        self.progress = (0, 0)

    # ---- kill switch -------------------------------------------------------------------------
    @property
    def kill_engaged(self) -> bool:
        return self.settings.kill_file.exists()

    def engage_kill_file(self, reason: str = "manual") -> None:
        self.settings.kill_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings.kill_file.write_text(f"{utcnow().isoformat()} {reason}\n", encoding="utf-8")

    def reset_kill(self) -> None:
        self.settings.kill_file.unlink(missing_ok=True)

    async def kill(self, reason: str = "manual") -> list[Order]:
        """Engage the kill switch. Always completes; safe to call when nothing is running."""
        self.engage_kill_file(reason)
        canceled: list[Order] = []
        if self.bot is not None:
            canceled = await self.bot.kill()
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        return canceled

    # ---- lifecycle ---------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(
        self,
        strategy: Strategy,
        risk: RiskConfig,
        symbol: str,
        resolution: str,
        initial_quote: Decimal | None = None,
        speed_s: float = 1.0,
        start_fraction: float = 0.55,
        real: bool = False,
    ) -> None:
        if self.running:
            raise RunnerError("a bot is already running; stop it first")
        if self.kill_engaged:
            raise RunnerError("kill switch is engaged; reset it first")
        quote_start_for = {
            "TMN": self.settings.paper_start_tmn,
            "USDT": self.settings.paper_start_usdt,
        }
        fees = FeeModel(self.settings.fee_maker, self.settings.fee_taker)
        self.speed_s, self.error, self.started_at = speed_s, None, utcnow()
        if real:
            # REAL MONEY. Every live condition is re-checked here and again on every order.
            blockers = live_blockers(self.settings)
            if blockers:
                raise RunnerError("live trading blocked: " + "; ".join(blockers))
            if not isinstance(self.live, WallexClient):
                raise RunnerError("real trading needs the Wallex client (DATA_SOURCE=wallex)")
            await self._start_live(
                strategy, risk, symbol, resolution, initial_quote, fees, quote_start_for, real=True
            )
            return
        if self.settings.data_source == "wallex":
            if self.live is None:
                raise RunnerError("DATA_SOURCE=wallex but no live market-data client")
            await self._start_live(strategy, risk, symbol, resolution, initial_quote, fees, quote_start_for)
            return
        market = self.replay.markets[symbol]
        series = self.replay.series(symbol, resolution)
        if len(series) < 50:
            raise RunnerError(f"not enough {resolution} data for {symbol}")
        start = max(strategy.warmup + 5, min(len(series) - 10, int(len(series) * start_fraction)))
        quote_start = initial_quote or quote_start_for.get(market.quote, ZERO)
        clock = SimClock(series[start].ts)
        self.paper = PaperExchange(
            self.replay,
            {symbol: market},
            fees,
            self.settings.slippage_bps,
            {market.quote: quote_start, market.base: ZERO},
            self.settings.fill_participation,
            clock,
        )
        self.paper.set_last_price(symbol, series[start - 1].close)
        self.bot = Bot(
            strategy,
            self._risk(risk, market, fees),
            self.paper,
            market,
            resolution,
            settings=self.settings,
            clock=clock,
        )
        self.bot.candles = list(series[max(0, start - self.bot.window) : start])
        self.mode = "paper-replay"
        self.progress = (0, len(series) - start)
        self.task = asyncio.create_task(self._loop(series[start:], resolution))

    def _risk(self, risk: RiskConfig, market: Market, fees: FeeModel) -> RiskManager:
        rm = RiskManager(risk, market, cost_buffer(fees, self.settings.slippage_bps))
        if self.settings.daily_loss_limit_pct is not None:
            # The env limit is a ceiling: a strategy may be stricter, never looser.
            cur = rm.cfg.daily_loss_limit_pct
            env = self.settings.daily_loss_limit_pct
            rm.cfg.daily_loss_limit_pct = min(cur, env) if cur else env
        return rm

    async def _start_live(
        self,
        strategy: Strategy,
        risk: RiskConfig,
        symbol: str,
        resolution: str,
        initial_quote: Decimal | None,
        fees: FeeModel,
        quote_start_for: dict[str, Decimal],
        real: bool = False,
    ) -> None:
        """Live Wallex data: signals on real closed candles. Paper mode fills on the real book; `real`
        sends guarded LIMIT orders to Wallex (only reachable when every live condition holds)."""
        assert self.live is not None
        markets = {m.symbol: m for m in await self.live.get_markets()}
        if symbol not in markets:
            raise RunnerError(f"{symbol} is not an active spot market")
        market = markets[symbol]
        step = resolution_delta(resolution)
        warm = max(strategy.warmup + 5, 60)
        history = await self.live.get_candles(symbol, resolution, utcnow() - step * (warm * 2), utcnow())
        if len(history) < strategy.warmup + 1:
            raise RunnerError(f"not enough live {resolution} history for {symbol}")
        rm = self._risk(risk, market, fees)
        if real:
            # The hard per-order cap from the environment also caps the strategy's own sizing.
            cap = self.settings.max_order_for_quote(market.quote)
            if cap is not None:
                rm.cfg.max_order_quote = min(rm.cfg.max_order_quote or cap, cap)
            self.paper = None
            self.bot = Bot(
                strategy,
                rm,
                self.live,
                market,
                resolution,
                settings=self.settings,
                fill_on_candle=False,
                order_ttl_s=self.settings.live_order_ttl_s,
                max_data_age_s=self.settings.stale_data_s,
            )
        else:
            quote_start = initial_quote or quote_start_for.get(market.quote, ZERO)
            self.paper = PaperExchange(
                self.live,
                {symbol: market},
                fees,
                self.settings.slippage_bps,
                {market.quote: quote_start, market.base: ZERO},
                self.settings.fill_participation,
            )
            self.paper.set_last_price(symbol, history[-1].close)
            self.bot = Bot(
                strategy,
                rm,
                self.paper,
                market,
                resolution,
                settings=self.settings,
                fill_on_candle=False,
                max_data_age_s=self.settings.stale_data_s,
            )
        self.bot.candles = list(history)
        self.mode = "live" if real else "paper-live"
        self.progress = (0, 0)
        self.task = asyncio.create_task(self._live_loop(symbol, resolution, history[-1].ts))

    async def _live_loop(self, symbol: str, resolution: str, last_ts: Any) -> None:
        assert self.bot is not None and self.live is not None
        step = resolution_delta(resolution)
        failures = 0
        try:
            while True:
                if self.kill_engaged:
                    await self.bot.kill()
                    return
                try:
                    book = await self.live.get_order_book(symbol)
                    book_ok = book_is_sane(book)
                    if self.paper is not None and book_ok:
                        self.paper.on_book(book)  # fill pending paper orders against the real book
                    await self.bot.sync_orders()
                    if book.mid is not None and book_ok:
                        self.bot.last_price = book.mid
                    fresh = await self.live.get_candles(symbol, resolution, utcnow() - step * 5, utcnow())
                    feed_age = (utcnow() - (max([last_ts, *(c.ts for c in fresh)]) + step)).total_seconds()
                    silent = feed_age > step.total_seconds() + self.settings.stale_data_s
                    self.bot.feed_stale = silent or not book_ok
                    self.bot.risk.stale = self.bot.risk.stale or self.bot.feed_stale
                    for candle in fresh:
                        if candle.ts > last_ts:
                            await self.bot.on_candle(candle)
                            last_ts = candle.ts
                            self.progress = (self.progress[0] + 1, 0)
                    failures = 0
                    self.error = None
                    if not book_ok:
                        self.error = "order book is empty or crossed; no new buys until it looks sane"
                    elif silent:
                        self.error = f"no new {resolution} candle for {int(feed_age)} s; no new buys"
                except (httpx.HTTPError, WallexAPIError) as e:
                    failures += 1
                    self.error = f"market data unavailable ({type(e).__name__}); retrying"
                    if failures >= 10:
                        raise  # stale data for too long: stop trading safely
                await asyncio.sleep(self.settings.live_poll_s * min(failures + 1, 6))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            await self.bot.kill()

    async def _loop(self, candles: list[Any], resolution: str) -> None:
        assert self.bot is not None
        step = resolution_delta(resolution)
        try:
            for i, candle in enumerate(candles):
                if self.kill_engaged:
                    await self.bot.kill()
                    return
                self.replay.set_cursor(candle.ts + step)
                await self.bot.on_candle(candle)
                self.progress = (i + 1, len(candles))
                await asyncio.sleep(self.speed_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            await self.bot.kill()

    async def stop(self) -> None:
        """Stop the loop and cancel open orders, without engaging the kill switch."""
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        if self.bot is not None:
            self.bot.stopped = True
            await self.bot.exchange.cancel_all(self.bot.symbol)

    async def status(self, log_limit: int = 50) -> dict[str, Any]:
        base: dict[str, Any] = {
            "running": self.running,
            "mode": self.mode,
            "kill_engaged": self.kill_engaged,
            "error": self.error,
            "speed_s": self.speed_s,
            "progress": {"done": self.progress[0], "total": self.progress[1]},
            "live_trading": self.mode == "live" and self.running,
            "data_stale": self.bot is not None and self.bot.risk.stale,
        }
        if self.bot is None:
            return {**base, "bot": None, "log": [], "equity_curve": []}
        curve = self.bot.equity_curve[-300:]
        return {
            **base,
            "bot": await self.bot.snapshot(),
            "log": [e.to_dict() for e in reversed(self.bot.log[-log_limit:])],
            "equity_curve": [
                {"ts": p.ts.isoformat(), "equity": float(p.equity), "price": float(p.price)} for p in curve
            ],
        }
