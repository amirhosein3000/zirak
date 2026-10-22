"""Performance metrics computed from a bot's equity curve and trade log."""

from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from zirak.engine.bot import EquityPoint
from zirak.models import RESOLUTION_SECONDS

SECONDS_PER_YEAR = 365 * 24 * 3600


@dataclass(frozen=True)
class Metrics:
    start_equity: float
    end_equity: float
    pnl: float
    return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate_pct: float
    trades: int  # completed sells (exits)
    orders: int
    exposure_pct: float  # share of candles with an open position
    fees_paid_quote: float
    buy_hold_return_pct: float
    buy_hold_max_drawdown_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def max_drawdown_pct(values: list[float]) -> float:
    peak, worst = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return worst * 100


def sharpe_ratio(values: list[float], resolution: str) -> float:
    """Annualised Sharpe of per-candle returns (risk-free rate 0)."""
    if len(values) < 3:
        return 0.0
    rets = [b / a - 1 for a, b in itertools.pairwise(values) if a > 0]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    if var <= 0:
        return 0.0
    periods = SECONDS_PER_YEAR / RESOLUTION_SECONDS[resolution]
    return mean / math.sqrt(var) * math.sqrt(periods)


def compute_metrics(
    curve: list[EquityPoint],
    exits: list[Decimal],
    orders: int,
    fees_quote: Decimal,
    resolution: str,
    taker_fee: Decimal,
) -> Metrics:
    eq = [float(p.equity) for p in curve]
    prices = [float(p.price) for p in curve]
    fee = float(taker_fee)
    start = eq[0] if eq else 0.0
    # A position still open at the end is valued as if sold at the last close, paying the taker fee
    # (buy-and-hold below pays the same exit fee), so open trades can't flatter the result.
    exit_cost = float(curve[-1].position_qty * curve[-1].price) * fee if curve else 0.0
    end = eq[-1] - exit_cost if eq else 0.0
    wins = sum(1 for x in exits if x > 0)
    exposure = sum(1 for p in curve if p.position_qty > 0) / len(curve) * 100 if curve else 0.0
    # Buy and hold: buy at the first price, sell at the last, paying the taker fee twice.
    if prices:
        bh = (prices[-1] / prices[0]) * (1 - fee) * (1 - fee) - 1
        bh_curve = [start * p / prices[0] for p in prices]
    else:
        bh, bh_curve = 0.0, []
    return Metrics(
        start_equity=start,
        end_equity=end,
        pnl=end - start,
        return_pct=(end / start - 1) * 100 if start > 0 else 0.0,
        max_drawdown_pct=max_drawdown_pct(eq),
        sharpe=sharpe_ratio(eq, resolution),
        win_rate_pct=wins / len(exits) * 100 if exits else 0.0,
        trades=len(exits),
        orders=orders,
        exposure_pct=exposure,
        fees_paid_quote=float(fees_quote),
        buy_hold_return_pct=bh * 100,
        buy_hold_max_drawdown_pct=max_drawdown_pct(bh_curve),
    )
