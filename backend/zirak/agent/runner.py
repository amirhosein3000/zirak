"""Drivers for the agent: backtest (history), shadow (live data, paper fills) and live (real orders).

All three build the same `Agent` and call the same `on_bar` / `on_tick`; only the exchange behind it and
the source of candles change. Every run writes a journal directory (see journal.py) and a report.
"""

from __future__ import annotations

import asyncio
import bisect
import contextlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from zirak.agent.config import AgentConfig
from zirak.agent.engine import Agent, Position
from zirak.agent.features import feature_frame, implied_closes
from zirak.agent.journal import Journal, dumps
from zirak.agent.labeling import Costs, build_dataset
from zirak.agent.model import MetaModel
from zirak.agent.posture import Posture, PostureAgent
from zirak.agent.report import build_report
from zirak.agent.tools import make_tools
from zirak.config import Settings
from zirak.engine.bot import SimClock
from zirak.exchange.base import ExchangeClient
from zirak.exchange.paper import PaperExchange
from zirak.exchange.replay import ReplayExchange
from zirak.fees import FeeModel
from zirak.llm.provider import ToolLLM
from zirak.models import Candle, Market, Side, resolution_delta, utcnow


def costs_from(settings: Settings, fees: tuple[Decimal, Decimal] | None = None) -> Costs:
    """Fees as fractions. `fees` = (maker, taker) read from the account when available."""
    maker, taker = fees if fees else (settings.fee_maker, settings.fee_taker)
    return Costs(taker=float(taker), maker=float(maker), slippage=float(settings.slippage_bps) / 10000)


def train_model(
    cfg: AgentConfig, series: dict[str, list[Candle]], costs: Costs, until: datetime | None = None
) -> MetaModel:
    """Fit the meta-labeler on candidates whose outcome is known before `until` (no look-ahead)."""
    step = resolution_delta(cfg.resolution)
    lo = (until - timedelta(days=cfg.model.train_days)) if until else None
    cut: dict[str, list[Candle]] = {}
    for sym, cs in series.items():
        sel = [c for c in cs if (until is None or c.ts + step <= until) and (lo is None or c.ts >= lo)]
        if sel:
            cut[sym] = sel
    traded = {s: c for s, c in cut.items() if s in cfg.markets}
    context = {s: c for s, c in cut.items() if s not in cfg.markets}
    data = build_dataset({**traded, **context}, costs, max(2.5 * costs.round_trip_pct(), 0.5))
    if len(data):
        data = data[data["symbol"].isin(cfg.markets) & data["setup"].isin(cfg.setups)]
    m = cfg.model
    model = MetaModel(m.min_prob, m.min_ev_pct, m.kelly_ref, m.min_rows)
    model.fit(data, costs.round_trip_pct())
    return model


# ---- backtest ------------------------------------------------------------------------------------
async def run_backtest(
    cfg: AgentConfig,
    series: dict[str, list[Candle]],
    markets: dict[str, Market],
    settings: Settings,
    run_dir: Path,
    start: datetime | None = None,
    end: datetime | None = None,
    walk_forward: bool = True,
    model: MetaModel | None = None,
    recorded_postures: list[Posture] | None = None,
) -> dict[str, Any]:
    """Replay history through the agent. Walk-forward: the model is retrained every `retrain_hours`
    on data that was already closed at that moment, so the backtest never sees its own future."""
    step = resolution_delta(cfg.resolution)
    costs = costs_from(settings)
    ref = cfg.markets[0]
    timeline = [c.ts for c in series[ref]]
    if start is None:
        start = timeline[0] + step * max(260, len(timeline) // 3)  # the first third trains the first model
    timeline = [t for t in timeline if t >= start and (end is None or t <= end)]
    if len(timeline) < 2:
        raise ValueError("not enough candles for the requested period")
    replay = ReplayExchange({(s, cfg.resolution): cs for s, cs in series.items()}, markets=markets)
    clock = SimClock(timeline[0])
    paper = PaperExchange(
        replay,
        {s: markets[s] for s in cfg.markets},
        FeeModel(Decimal(str(costs.maker)), Decimal(str(costs.taker))),
        settings.slippage_bps,
        {"TMN": Decimal(str(cfg.initial_equity_tmn))},
        settings.fill_participation,
        clock,
    )
    journal = Journal(run_dir)

    async def trainer(now: datetime) -> MetaModel:
        return await asyncio.to_thread(train_model, cfg, series, costs, now)

    agent = Agent(
        cfg,
        paper,
        markets,
        model or MetaModel(),
        journal,
        costs,
        clock,
        settings,
        recorded_postures=recorded_postures,
        trainer=trainer if walk_forward and model is None else None,
    )
    agent.precomputed = {s: feature_frame(series[s], implied_closes(series, s)) for s in cfg.markets}
    agent.save_model()
    journal.manifest(
        {
            "mode": "backtest",
            "config": cfg.model_dump(mode="json"),
            "start": timeline[0],
            "end": timeline[-1],
            "walk_forward": walk_forward,
            "costs": costs.__dict__,
        }
    )
    times = {s: [c.ts for c in cs] for s, cs in series.items()}
    for ts in timeline:
        now = ts + step
        clock.now = now
        visible: dict[str, list[Candle]] = {}
        for sym, cs in series.items():
            n = bisect.bisect_right(times[sym], ts)
            visible[sym] = cs[:n]
            if sym in cfg.markets and n and cs[n - 1].ts == ts:
                paper.on_candle(sym, cs[n - 1])  # orders from the previous bar fill on this candle
        replay.set_cursor(now)
        await agent.on_bar(now, visible)
    report = build_report(run_dir, cfg, mode="backtest")
    (run_dir / "report.json").write_text(dumps(report), encoding="utf-8")
    return report


# ---- shadow / live -------------------------------------------------------------------------------
async def run_live(
    cfg: AgentConfig,
    settings: Settings,
    run_dir: Path,
    mode: str,
    data: ExchangeClient,
    model: MetaModel,
    posture_llm: ToolLLM | None = None,
    stop_after_s: float | None = None,
    on_status: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """mode "shadow": live Wallex data, paper fills on the real order book. mode "live": real orders."""
    from zirak.exchange.wallex import WallexClient

    assert mode in ("shadow", "live")
    step = resolution_delta(cfg.resolution)
    all_markets = {m.symbol: m for m in await data.get_markets()}
    traded = [s for s in cfg.markets if s in all_markets]
    package: dict[str, Any] | None = None
    fees: tuple[Decimal, Decimal] | None = None
    if isinstance(data, WallexClient) and settings.wallex_api_key:
        if settings.wallex_prop_package_id:
            banned = set(await data.get_unavailable_markets(settings.wallex_prop_package_id))
            traded = [s for s in traded if s not in banned]
        with contextlib.suppress(Exception):
            rates = await data.get_fees()
            pairs = [rates[s] for s in traded if s in rates]
            if pairs:
                maker = max(p[0] for p in pairs)
                taker = max(p[1] for p in pairs)
                # UNVERIFIED unit: a rate above 5 % can only be a percentage
                scale = Decimal(100) if taker > Decimal("0.05") else Decimal(1)
                fees = (maker / scale, taker / scale)
        if settings.wallex_credit_account:
            with contextlib.suppress(Exception):
                package = await data.get_active_package()
    if not traded:
        raise RuntimeError("none of the configured markets is tradable")
    cfg = cfg.model_copy(update={"markets": traded})
    costs = costs_from(settings, fees)
    markets = {s: all_markets[s] for s in cfg.all_markets if s in all_markets}
    clock = utcnow
    if mode == "shadow":
        exchange: ExchangeClient = PaperExchange(
            data,
            {s: markets[s] for s in cfg.markets},
            FeeModel(Decimal(str(costs.maker)), Decimal(str(costs.taker))),
            settings.slippage_bps,
            {"TMN": Decimal(str(cfg.initial_equity_tmn))},
            settings.fill_participation,
        )
    else:
        exchange = data
    journal = Journal(run_dir)
    agent = Agent(cfg, exchange, markets, model, journal, costs, clock, settings, package=package)
    agent.save_model()
    if posture_llm is not None:
        agent.posture_agent = PostureAgent(posture_llm, make_tools(agent, data), cfg.markets)
    state = journal.load_state()
    if state:
        agent.restore(state)
    journal.manifest(
        {
            "mode": mode,
            "config": cfg.model_dump(mode="json"),
            "start": utcnow(),
            "costs": costs.__dict__,
            "fees_from_account": fees is not None,
            "package": package,
            "model": model.card.to_dict(),
            "resumed": state is not None,
        }
    )
    if mode == "live":
        await reconcile(agent)
    history_days = max(12.0, (240 * step.total_seconds()) / 86400 + 1)
    candles = {
        s: await data.get_candles(s, cfg.resolution, utcnow() - timedelta(days=history_days), utcnow())
        for s in markets
    }
    last_bar = max((cs[-1].ts for cs in candles.values() if cs), default=None)
    t0 = utcnow()
    failures = 0
    while not agent.stopped:
        if settings.kill_file.exists():
            await kill(agent, "KILL file")
            break
        now = utcnow()
        try:
            if isinstance(exchange, PaperExchange):
                for sym in {*agent.positions, *agent.pending}:
                    exchange.on_book(await data.get_order_book(sym))
            await agent.on_tick(now)
            # no new closed bar for a whole extra bar + STALE_DATA_S -> stale: entries pause, exits continue
            agent.data_stale = last_bar is not None and (now - (last_bar + step)).total_seconds() > (
                step.total_seconds() + settings.stale_data_s
            )
            if last_bar is None or now >= last_bar + step * 2:
                fresh = {s: await data.get_candles(s, cfg.resolution, now - step * 6, now) for s in markets}
                newest = None
                for s, cs in fresh.items():
                    seen = {c.ts for c in candles[s]}
                    candles[s] = [*candles[s], *[c for c in cs if c.ts not in seen]][-2000:]
                    if s in cfg.markets and cs:
                        newest = max(newest or cs[-1].ts, cs[-1].ts)
                if newest is not None and (last_bar is None or newest > last_bar):
                    last_bar = newest
                    t_bar = utcnow()
                    await agent.on_bar(t_bar, candles)
                    journal.bar(
                        {
                            "bar": newest,
                            "decided_at": utcnow(),
                            "latency_ms": round((utcnow() - (newest + step)).total_seconds() * 1000, 1),
                            "compute_ms": round((utcnow() - t_bar).total_seconds() * 1000, 1),
                            "closes": {s: cs[-1].close for s, cs in candles.items() if cs},
                        }
                    )
            if package is not None and isinstance(data, WallexClient) and now.minute % 10 == 0:
                with contextlib.suppress(Exception):
                    agent.package = await data.get_active_package()
            failures = 0
        except Exception as e:
            failures += 1
            agent.errors += 1
            journal.order({"ts": now, "loop_error": repr(e)})
            if failures >= 20:
                await kill(agent, f"20 consecutive errors: {e!r}")
                break
        if agent.guard.killed and not agent.positions and not agent.pending:
            settings.kill_file.parent.mkdir(parents=True, exist_ok=True)
            settings.kill_file.write_text(f"{utcnow().isoformat()} agent guard: {agent.guard.kill_reason}\n")
            agent.stopped = True
        if on_status is not None:
            await on_status(agent.snapshot_state())
        if stop_after_s is not None and (utcnow() - t0).total_seconds() >= stop_after_s:
            break
        await asyncio.sleep(cfg.execution.poll_s * min(failures + 1, 6))
    report = build_report(run_dir, cfg, mode=mode)
    (run_dir / "report.json").write_text(dumps(report), encoding="utf-8")
    return report


async def kill(agent: Agent, reason: str) -> None:
    """Kill switch: cancel every open order and stop. Positions are left as they are (use `flatten`)."""
    agent.stopped = True
    with contextlib.suppress(Exception):
        await agent.ex.cancel_all()
    agent.journal.decision(
        {
            "ts": agent.clock(),
            "kind": "kill",
            "reason": reason,
            "reason_fa": "کلید توقف اضطراری: همهٔ سفارش‌های باز لغو و ربات متوقف شد.",
        }
    )
    agent._save()


async def reconcile(agent: Agent) -> None:
    """After a restart: the account is the truth. Cancel orders we don't know, drop positions whose coins
    are gone, adopt coins the state doesn't know (with a fresh stop) so nothing is left unmanaged."""
    known = {p.tp_order_id for p in agent.positions.values()} | {
        p.exit_order_id for p in agent.positions.values()
    }
    known |= {pe.order_id for pe in agent.pending.values()}
    for o in await agent.ex.get_open_orders():
        if o.id not in known:
            await agent._cancel(o.symbol, o.id)
            agent.journal.decision(
                {
                    "ts": agent.clock(),
                    "kind": "reconcile",
                    "symbol": o.symbol,
                    "reason_fa": f"سفارش ناشناخته {o.id} پس از راه‌اندازی دوباره لغو شد.",
                }
            )
    bal = await agent.ex.get_balances()
    for sym, pos in list(agent.positions.items()):
        b = bal.get(agent.markets[sym].base)
        have = b.total if b else Decimal(0)
        if have < (pos.qty - pos.sold) * Decimal("0.5"):
            agent.positions.pop(sym)
            agent.journal.decision(
                {
                    "ts": agent.clock(),
                    "kind": "reconcile",
                    "symbol": sym,
                    "reason_fa": "موقعیت ذخیره‌شده در حساب پیدا نشد (احتمالاً در زمان قطعی بسته شده).",
                }
            )
    for sym in agent.cfg.markets:
        m = agent.markets[sym]
        b = bal.get(m.base)
        if sym in agent.positions or b is None or b.total < m.min_qty:
            continue
        book = await agent.ex.get_order_book(sym)
        px = book.best_bid
        if px is None or b.total * px < m.min_notional:
            continue
        agent.last_price[sym] = px
        agent.positions[sym] = Position(
            sym,
            "adopted",
            "reconcile",
            m.round_qty(b.total),
            b.total * px,
            px,
            m.round_price(px * Decimal("0.98"), Side.SELL),
            m.round_price(px * Decimal("1.015"), Side.BUY),
            utcnow().isoformat(),
            8,
        )
        agent.journal.decision(
            {
                "ts": agent.clock(),
                "kind": "reconcile",
                "symbol": sym,
                "qty": b.total,
                "reason_fa": "دارایی بدون موقعیت ثبت‌شده پیدا شد؛ با حد ضرر ۲٪ و حد سود ۱٫۵٪ مدیریت می‌شود.",
            }
        )
    agent._save()
