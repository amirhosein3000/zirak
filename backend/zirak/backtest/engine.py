"""Backtester. It does not have its own trading logic: it replays candles through the exact same
Bot -> Strategy -> RiskManager -> Executor -> PaperExchange path used for paper/live trading.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from zirak.backtest.metrics import compute_metrics
from zirak.engine.bot import Bot, SimClock
from zirak.engine.risk import RiskConfig, RiskManager
from zirak.exchange.paper import MARKET_BUY_BUFFER, PaperExchange
from zirak.exchange.replay import ReplayExchange
from zirak.fees import BPS, FeeModel
from zirak.models import ZERO, Candle, Market, Side, resolution_delta
from zirak.strategy.base import Strategy

MAX_CURVE_POINTS = 800


@dataclass
class BacktestSetup:
    market: Market
    resolution: str
    strategy: Strategy
    risk: RiskConfig
    fees: FeeModel
    slippage_bps: Decimal
    initial_quote: Decimal
    participation: Decimal = Decimal("0.10")
    meta: dict[str, Any] = field(default_factory=dict)


def cost_buffer(fees: FeeModel, slippage_bps: Decimal) -> Decimal:
    """Quote held back when sizing buys, so a market buy is always fully funded."""
    return fees.taker + slippage_bps / BPS + MARKET_BUY_BUFFER + Decimal("0.001")


async def run_backtest_async(candles: list[Candle], setup: BacktestSetup) -> dict[str, Any]:
    if len(candles) < 2:
        raise ValueError("need at least 2 candles to backtest")
    m, res = setup.market, setup.resolution
    replay = ReplayExchange({(m.symbol, res): candles}, markets={m.symbol: m})
    clock = SimClock(candles[0].ts)
    paper = PaperExchange(
        replay,
        {m.symbol: m},
        setup.fees,
        setup.slippage_bps,
        {m.quote: setup.initial_quote, m.base: ZERO},
        setup.participation,
        clock,
    )
    risk = RiskManager(setup.risk, m, cost_buffer(setup.fees, setup.slippage_bps))
    bot = Bot(setup.strategy, risk, paper, m, res, clock=clock)
    step = resolution_delta(res)
    for candle in candles:
        replay.set_cursor(candle.ts + step)
        await bot.on_candle(candle)

    orders = [o for o in paper.all_orders() if o.filled_qty > 0]
    fees_quote = sum(
        ((f.fee * f.price) if f.side is Side.BUY else f.fee for o in orders for f in o.fills), ZERO
    )
    metrics = compute_metrics(
        bot.equity_curve, bot.ledger.exits, len(orders), fees_quote, res, setup.fees.taker
    )
    return build_report(bot, setup, candles, metrics.to_dict())


def run_backtest(candles: list[Candle], setup: BacktestSetup) -> dict[str, Any]:
    return asyncio.run(run_backtest_async(candles, setup))


def _downsample(n: int) -> list[int]:
    if n <= MAX_CURVE_POINTS:
        return list(range(n))
    stride = n / MAX_CURVE_POINTS
    idx = sorted({int(i * stride) for i in range(MAX_CURVE_POINTS)} | {n - 1})
    return idx


def build_report(
    bot: Bot, setup: BacktestSetup, candles: list[Candle], metrics: dict[str, Any]
) -> dict[str, Any]:
    curve = bot.equity_curve
    eq = [float(p.equity) for p in curve]
    peak, dd = 0.0, []
    for v in eq:
        peak = max(peak, v)
        dd.append((v / peak - 1) * 100 if peak > 0 else 0.0)
    first_price = float(curve[0].price) if curve else 1.0
    start = eq[0] if eq else 0.0
    points = [
        {
            "ts": curve[i].ts.isoformat(),
            "equity": round(eq[i], 6),
            "drawdown_pct": round(dd[i], 4),
            "price": float(curve[i].price),
            "buy_hold": round(start * float(curve[i].price) / first_price, 6),
        }
        for i in _downsample(len(curve))
    ]
    return {
        "id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(UTC).isoformat(),
        "symbol": setup.market.symbol,
        "quote": setup.market.quote,
        "resolution": setup.resolution,
        "period": {
            "start": candles[0].ts.isoformat(),
            "end": candles[-1].ts.isoformat(),
            "candles": len(candles),
        },
        "strategy": setup.strategy.describe(),
        "risk": setup.risk.to_dict(),
        "costs": {
            "fee_taker_pct": str(setup.fees.taker * 100),
            "fee_maker_pct": str(setup.fees.maker * 100),
            "slippage_bps": str(setup.slippage_bps),
            "participation": str(setup.participation),
        },
        "initial_quote": str(setup.initial_quote),
        "metrics": metrics,
        "open_position_qty": str(bot.ledger.qty),
        "equity_curve": points,
        "trades": [e.to_dict() for e in bot.log],
        "meta": setup.meta,
    }


def save_report(report: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['id']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
