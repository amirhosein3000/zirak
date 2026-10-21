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

from zirak.backtest.engine import cost_buffer
from zirak.config import Settings
from zirak.engine.bot import Bot, SimClock
from zirak.engine.risk import RiskConfig, RiskManager
from zirak.exchange.paper import PaperExchange
from zirak.exchange.replay import ReplayExchange
from zirak.fees import FeeModel
from zirak.models import ZERO, Order, resolution_delta, utcnow
from zirak.strategy.base import Strategy


class RunnerError(RuntimeError):
    pass


class BotRunner:
    def __init__(self, settings: Settings, replay: ReplayExchange) -> None:
        self.settings = settings
        self.replay = replay
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
    ) -> None:
        if self.running:
            raise RunnerError("a bot is already running; stop it first")
        if self.kill_engaged:
            raise RunnerError("kill switch is engaged; reset it first")
        if self.settings.data_source != "replay":
            # Live market data needs WallexClient, which waits for docs/wallex-api.
            raise RunnerError("live data source is not available yet (docs/wallex-api missing)")
        market = self.replay.markets[symbol]
        series = self.replay.series(symbol, resolution)
        if len(series) < 50:
            raise RunnerError(f"not enough {resolution} data for {symbol}")
        start = max(strategy.warmup + 5, min(len(series) - 10, int(len(series) * start_fraction)))
        quote_start = initial_quote or (
            self.settings.paper_start_tmn if market.quote == "TMN" else self.settings.paper_start_usdt
        )
        fees = FeeModel(self.settings.fee_maker, self.settings.fee_taker)
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
        rm = RiskManager(risk, market, cost_buffer(fees, self.settings.slippage_bps))
        if self.settings.daily_loss_limit_pct is not None:
            # The env limit is a ceiling: a strategy may be stricter, never looser.
            cur = rm.cfg.daily_loss_limit_pct
            rm.cfg.daily_loss_limit_pct = (
                min(cur, self.settings.daily_loss_limit_pct) if cur else (self.settings.daily_loss_limit_pct)
            )
        self.bot = Bot(strategy, rm, self.paper, market, resolution, settings=self.settings, clock=clock)
        self.bot.candles = list(series[max(0, start - self.bot.window) : start])
        self.speed_s, self.error, self.started_at = speed_s, None, utcnow()
        self.progress = (0, len(series) - start)
        self.task = asyncio.create_task(self._loop(series[start:], resolution))

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
            "live_trading": False,
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
