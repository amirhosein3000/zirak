"""Competition mode: a headless runner for a PnL / drawdown contest.

Several strategies trade side by side in paper mode (replayed data, or live Wallex data with
DATA_SOURCE=wallex). Capital is split into sleeves: every entry gets `capital_pct` of the starting
balance of its market's quote currency in its own paper sub-account, so strategies can't fight over
the same funds. Each entry runs the normal Bot -> RiskManager -> Executor path with the env daily loss
limit as a ceiling.

A supervisor adds team-level limits on top: when total equity falls `max_drawdown_pct` below its peak,
or `daily_loss_pct` below today's start, it engages the kill switch (KILL file), which stops every entry
and cancels all orders. `zirak kill` from any terminal does the same.

It writes `<DATA_DIR>/competition/<name>/`:
- `performance.json` (rewritten atomically every few seconds: equity, PnL, drawdown, trades per entry),
- `trades.jsonl` (one line per decision, appended), `equity.csv` (timestamp, total equity in TMN).
USDT equity is converted to Toman with the latest USDTTMN price (shown in the file).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from zirak.config import Settings
from zirak.engine.risk import RiskConfig
from zirak.engine.runner import BotRunner, RunnerError
from zirak.exchange.base import ExchangeClient
from zirak.exchange.replay import ReplayExchange
from zirak.models import HUNDRED, ZERO, utcnow
from zirak.strategy.base import Strategy
from zirak.strategy.registry import build_strategy
from zirak.strategy.spec import RuleStrategy, StrategySpec


class EntryIn(BaseModel):
    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    strategy: str = "rsi_reversion"
    params: dict[str, Any] = Field(default_factory=dict)
    spec: dict[str, Any] | None = None
    symbol: str = "BTCTMN"
    resolution: str = "1h"
    capital_pct: Decimal = Field(Decimal(25), gt=0, le=100)


class CompetitionIn(BaseModel):
    name: str = Field("default", pattern=r"^[A-Za-z0-9_-]+$", max_length=40)
    entries: list[EntryIn] = Field(min_length=1, max_length=10)
    risk: dict[str, Any] = Field(default_factory=dict)  # RiskConfig for every entry
    max_drawdown_pct: Decimal = Field(Decimal(10), gt=0, le=100)  # team-level stop
    daily_loss_pct: Decimal = Field(Decimal(3), gt=0, le=100)  # team-level stop, per UTC day
    speed_s: float = Field(0.2, ge=0.0, le=30)  # replay only: seconds per candle
    write_every_s: float = Field(5.0, ge=0.05, le=300)


# Conservative default team: small sleeves, different markets/styles, cash kept in reserve.
DEFAULT_CONFIG: dict[str, Any] = {
    "name": "default",
    "entries": [
        {
            "name": "btc_rsi",
            "strategy": "rsi_reversion",
            "symbol": "BTCTMN",
            "resolution": "1h",
            "capital_pct": 25,
        },
        {
            "name": "eth_rsi",
            "strategy": "rsi_reversion",
            "symbol": "ETHTMN",
            "resolution": "1h",
            "capital_pct": 20,
        },
        {
            "name": "btc_trend",
            "strategy": "ema_cross",
            "symbol": "BTCTMN",
            "resolution": "1h",
            "capital_pct": 20,
        },
    ],
    "risk": {"stop_loss_pct": 3, "max_position_pct": 80, "daily_loss_limit_pct": 2, "cooldown_candles": 2},
    "max_drawdown_pct": 8,
    "daily_loss_pct": 3,
}


def _strategy(e: EntryIn) -> Strategy:
    if e.strategy == "rules":
        if e.spec is None:
            raise ValueError(f"{e.name}: strategy 'rules' needs a spec")
        return RuleStrategy(StrategySpec.model_validate(e.spec))
    return build_strategy(e.strategy, e.params or None)


@dataclass
class Competition:
    settings: Settings
    config: CompetitionIn
    replay: ReplayExchange
    live: ExchangeClient | None = None
    runners: dict[str, BotRunner] = field(default_factory=dict)
    peak: Decimal = ZERO
    day: Any = None
    day_start: Decimal = ZERO
    stopped_reason: str | None = None
    task: asyncio.Task[None] | None = None
    _logged: dict[str, int] = field(default_factory=dict)

    @property
    def out_dir(self) -> Path:
        return self.settings.data_dir / "competition" / self.config.name

    async def start(self) -> None:
        if self.settings.kill_file.exists():
            raise RunnerError("kill switch is engaged; reset it first")
        totals: dict[str, Decimal] = {}
        for e in self.config.entries:
            market = self.replay.markets.get(e.symbol)
            quote = market.quote if market else "TMN"
            totals[quote] = totals.get(quote, ZERO) + e.capital_pct
        over = [q for q, pct in totals.items() if pct > HUNDRED]
        if over:
            raise RunnerError(f"capital_pct adds up to more than 100 % for {', '.join(over)}")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        start_for = {"TMN": self.settings.paper_start_tmn, "USDT": self.settings.paper_start_usdt}
        risk = RiskConfig.from_dict(self.config.risk)
        try:
            for e in self.config.entries:
                runner = BotRunner(self.settings, self.replay.fork(), self.live)
                market = self.replay.markets.get(e.symbol)
                quote = market.quote if market else "TMN"
                capital = start_for.get(quote, ZERO) * e.capital_pct / HUNDRED
                await runner.start(
                    _strategy(e),
                    RiskConfig.from_dict(risk.to_dict()),
                    e.symbol,
                    e.resolution,
                    initial_quote=capital,
                    speed_s=self.config.speed_s,
                )
                self.runners[e.name] = runner
        except Exception:
            for r in self.runners.values():
                await r.stop()
            raise
        self.task = asyncio.create_task(self._supervise())

    @property
    def running(self) -> bool:
        return any(r.running for r in self.runners.values())

    async def _supervise(self) -> None:
        try:
            while True:
                perf = await self.performance()
                self._write(perf)
                if self.stopped_reason is None and self.running:
                    reason = self._breach(perf)
                    if reason:
                        self.stopped_reason = reason
                        await self.kill(reason)
                        self._write(await self.performance())
                        return
                if not self.running:
                    self._write(await self.performance())
                    return
                await asyncio.sleep(self.config.write_every_s)
        except asyncio.CancelledError:
            raise

    def _breach(self, perf: dict[str, Any]) -> str | None:
        total = Decimal(perf["total_equity_tmn"])
        if total <= 0:
            return None
        self.peak = max(self.peak, total)
        today = utcnow().date() if self.live is not None else perf.get("data_day")
        if today != self.day:
            self.day, self.day_start = today, total
        dd = (self.peak - total) / self.peak * HUNDRED
        if dd >= self.config.max_drawdown_pct:
            return f"team drawdown {dd:.2f}% >= {self.config.max_drawdown_pct}%"
        if self.day_start > 0:
            loss = (self.day_start - total) / self.day_start * HUNDRED
            if loss >= self.config.daily_loss_pct:
                return f"team daily loss {loss:.2f}% >= {self.config.daily_loss_pct}%"
        return None

    async def usdt_tmn(self) -> Decimal | None:
        if self.live is not None:
            with contextlib.suppress(Exception):
                book = await self.live.get_order_book("USDTTMN")
                if book.mid:
                    return book.mid
            return None
        # Replay: the price at the time the entries have reached (the earliest cursor).
        cursors = [r.replay.cursor for r in self.runners.values() if r.replay.cursor is not None]
        view = self.replay.fork()
        view.set_cursor(min(cursors) if cursors else None)
        return view.last_close("USDTTMN")

    async def performance(self) -> dict[str, Any]:
        rate = await self.usdt_tmn()
        entries: list[dict[str, Any]] = []
        total = ZERO
        start_total = ZERO
        data_day = None
        for name, runner in self.runners.items():
            st = await runner.status(log_limit=0)
            bot = st["bot"]
            if bot is None:
                continue
            quote = runner.bot.market.quote if runner.bot else "TMN"
            to_tmn = Decimal(1) if quote == "TMN" else (rate or ZERO)
            eq, start = Decimal(bot["equity"]), Decimal(bot["start_equity"])
            total += eq * to_tmn
            start_total += start * to_tmn
            if runner.bot and runner.bot.equity_curve:
                data_day = runner.bot.equity_curve[-1].ts.date()
                curve = [p.equity for p in runner.bot.equity_curve]
                peak, dd = curve[0], ZERO
                for v in curve:
                    peak = max(peak, v)
                    dd = max(dd, (peak - v) / peak * HUNDRED if peak > 0 else ZERO)
            else:
                dd = ZERO
            exits = runner.bot.ledger.exits if runner.bot else []
            entries.append(
                {
                    "name": name,
                    "symbol": bot["symbol"],
                    "strategy": bot["strategy"]["key"],
                    "quote": quote,
                    "equity": bot["equity"],
                    "start_equity": bot["start_equity"],
                    "pnl": bot["pnl"],
                    "pnl_pct": bot["pnl_pct"],
                    "max_drawdown_pct": str(dd.quantize(Decimal("0.01"))),
                    "trades": len(exits),
                    "wins": sum(1 for x in exits if x > 0),
                    "position_qty": bot["position_qty"],
                    "halted": bot["halted"],
                    "killed": bot["killed"],
                    "running": st["running"],
                    "error": st["error"],
                    "candles_seen": bot["candles_seen"],
                }
            )
            self._append_trades(name, runner)
        pnl_pct = (total / start_total - 1) * HUNDRED if start_total > 0 else ZERO
        peak = max(self.peak, total)
        return {
            "name": self.config.name,
            "updated_at": utcnow().isoformat(),
            "mode": next(iter(self.runners.values())).mode if self.runners else None,
            "running": self.running,
            "stopped_reason": self.stopped_reason,
            "kill_engaged": self.settings.kill_file.exists(),
            "usdt_tmn": str(rate) if rate is not None else None,
            "total_equity_tmn": str(total.quantize(Decimal(1))),
            "start_equity_tmn": str(start_total.quantize(Decimal(1))),
            "pnl_pct": str(pnl_pct.quantize(Decimal("0.001"))),
            "drawdown_from_peak_pct": str(((peak - total) / peak * HUNDRED).quantize(Decimal("0.001")))
            if peak > 0
            else "0",
            "limits": {
                "max_drawdown_pct": str(self.config.max_drawdown_pct),
                "daily_loss_pct": str(self.config.daily_loss_pct),
                "per_entry_risk": self.config.risk,
            },
            "data_day": data_day,
            "entries": entries,
        }

    def _append_trades(self, name: str, runner: BotRunner) -> None:
        if runner.bot is None:
            return
        done = self._logged.get(name, 0)
        new = runner.bot.log[done:]
        # Only append decisions whose order has finished, so each line is final.
        final = []
        for e in new:
            if e.order_status in ("new", "partially_filled"):
                break
            final.append(e)
        if not final:
            return
        with (self.out_dir / "trades.jsonl").open("a", encoding="utf-8") as f:
            for e in final:
                f.write(json.dumps({"entry": name, **e.to_dict()}, ensure_ascii=False) + "\n")
        self._logged[name] = done + len(final)

    def _write(self, perf: dict[str, Any]) -> None:
        out = {**perf, "data_day": str(perf["data_day"]) if perf.get("data_day") else None}
        tmp = self.out_dir / "performance.json.tmp"
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.out_dir / "performance.json")
        eq = self.out_dir / "equity.csv"
        new = not eq.exists()
        with eq.open("a", encoding="utf-8") as f:
            if new:
                f.write("ts,total_equity_tmn,pnl_pct\n")
            f.write(f"{perf['updated_at']},{perf['total_equity_tmn']},{perf['pnl_pct']}\n")

    async def kill(self, reason: str = "manual") -> None:
        for r in self.runners.values():
            await r.kill(f"competition: {reason}")

    async def stop(self) -> None:
        for r in self.runners.values():
            await r.stop()
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        if self.runners:
            self._write(await self.performance())


# ---- API ---------------------------------------------------------------------------------------
router = APIRouter()


def _current(state: Any) -> Competition | None:
    return getattr(state, "competition", None)


@router.get("/default-config")
async def default_config() -> dict[str, Any]:
    return DEFAULT_CONFIG


@router.post("/start")
async def start(body: CompetitionIn, request: Request) -> dict[str, Any]:
    state = request.app.state.zirak
    cur = _current(state)
    if cur is not None and cur.running:
        raise HTTPException(409, "یک مسابقه در حال اجراست؛ اول آن را متوقف کنید.")
    if state.runner.running:
        raise HTTPException(409, "ربات کاغذی در حال اجراست؛ اول آن را متوقف کنید.")
    comp = Competition(state.settings, body, state.replay, state.live)
    try:
        await comp.start()
    except (RunnerError, ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from e
    state.competition = comp
    return await comp.performance()


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    cur = _current(request.app.state.zirak)
    if cur is None:
        return {"running": False, "entries": []}
    return await cur.performance()


@router.post("/stop")
async def stop(request: Request) -> dict[str, Any]:
    cur = _current(request.app.state.zirak)
    if cur is not None:
        await cur.stop()
        return await cur.performance()
    return {"running": False, "entries": []}


@router.post("/kill")
async def kill(request: Request) -> dict[str, Any]:
    cur = _current(request.app.state.zirak)
    if cur is None:
        await request.app.state.zirak.runner.kill("competition api")
        return {"running": False, "entries": [], "kill_engaged": True}
    await cur.kill("api")
    return await cur.performance()
