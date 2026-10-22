"""Walk-forward research: pick parameters on one window, trade them on the next unseen window, roll.

Only out-of-sample (OOS) results count. Every run goes through the normal backtester (same Bot,
RiskManager and PaperExchange as paper/live trading) with fees and slippage. Parameter grids are kept
small on purpose: a big grid finds luck, not edge.

A configuration survives only if, out of sample, it
  1. made at least `min_trades` round trips,
  2. made money (beat holding cash, i.e. return > 0),
  3. had a smaller max drawdown than buy-and-hold over the same test windows.
Beating buy-and-hold on return is reported but not required (a smoother ride with a positive return is
what most retail users need).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from zirak.backtest.engine import BacktestSetup, run_backtest_async
from zirak.engine.risk import RiskConfig
from zirak.fees import FeeModel
from zirak.models import Candle, Market
from zirak.strategy.base import Strategy
from zirak.strategy.registry import build_strategy
from zirak.strategy.spec import RuleStrategy, StrategySpec

#: per strategy key: parameter grid (cartesian product). "dip" = the Persian-sentence rule strategy.
GRIDS: dict[str, dict[str, list[Any]]] = {
    "ema_cross": {"fast": [8, 12, 20], "slow": [26, 50], "size_pct": [50]},
    "rsi_reversion": {"period": [14], "low": [25, 30, 35], "high": [55, 65], "size_pct": [40]},
    "grid": {"levels": [6, 10], "range_pct": [5, 8, 12]},
    "dca": {"every": [12, 24, 48], "size_pct": [5], "take_profit_pct": [3, 6], "max_entries": [10]},
    "dip": {"pct": [3, 5, 8], "lookback": [24], "take_profit_pct": [2, 3, 5], "size_pct": [10]},
}
DEFAULT_RISK: dict[str, Any] = {"stop_loss_pct": 5, "daily_loss_limit_pct": 5, "max_position_pct": 80}


def combos(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*(grid[k] for k in keys))]


def build(key: str, params: dict[str, Any], symbol: str, resolution: str) -> tuple[Strategy, RiskConfig]:
    if key == "dip":
        spec = StrategySpec.model_validate(
            {
                "symbol": symbol,
                "resolution": resolution,
                "entry": [{"kind": "drop_from_high", "pct": params["pct"], "lookback": params["lookback"]}],
                "position_size_pct": params["size_pct"],
                "take_profit_pct": params["take_profit_pct"],
                "stop_loss_pct": DEFAULT_RISK["stop_loss_pct"],
            }
        )
        risk = RiskConfig.from_dict({**DEFAULT_RISK, "take_profit_pct": params["take_profit_pct"]})
        return RuleStrategy(spec), risk
    return build_strategy(key, params), RiskConfig.from_dict(DEFAULT_RISK)


@dataclass
class Fold:
    train: tuple[str, str]
    test: tuple[str, str]
    params: dict[str, Any]
    is_return_pct: float
    oos_return_pct: float
    oos_max_dd_pct: float
    oos_trades: int
    bh_return_pct: float
    bh_max_dd_pct: float


@dataclass
class WalkForward:
    key: str
    symbol: str
    resolution: str
    folds: list[Fold] = field(default_factory=list)
    oos_return_pct: float = 0.0
    oos_max_dd_pct: float = 0.0
    oos_trades: int = 0
    is_return_pct: float = 0.0  # mean in-sample return of the chosen params
    bh_return_pct: float = 0.0
    bh_max_dd_pct: float = 0.0
    verdict: str = ""
    survives: bool = False
    chosen: dict[str, Any] = field(default_factory=dict)  # params chosen on the most recent window

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "folds"} | {
            "folds": [f.__dict__ for f in self.folds]
        }


def _objective(m: dict[str, Any]) -> float:
    if m["trades"] < 2:
        return float("-inf")
    return float(m["return_pct"]) + 0.5 * float(m["max_drawdown_pct"])  # drawdown is negative


async def _run(
    key: str,
    params: dict[str, Any],
    market: Market,
    resolution: str,
    candles: list[Candle],
    warmup: list[Candle],
    fees: FeeModel,
    slippage: Decimal,
    initial: Decimal,
) -> dict[str, Any]:
    strat, risk = build(key, params, market.symbol, resolution)
    setup = BacktestSetup(market, resolution, strat, risk, fees, slippage, initial)
    return await run_backtest_async(candles, setup, warmup=warmup)


def _stitch(curves: list[list[float]]) -> tuple[float, float]:
    """Compound fold equity curves (each normalised to its start) -> (total return %, max DD %)."""
    level, peak, worst = 1.0, 1.0, 0.0
    for curve in curves:
        if not curve or curve[0] <= 0:
            continue
        base = level
        for v in curve:
            level = base * v / curve[0]
            peak = max(peak, level)
            worst = min(worst, level / peak - 1)
    return (level - 1) * 100, worst * 100


async def walk_forward(
    key: str,
    market: Market,
    resolution: str,
    series: list[Candle],
    train: int,
    test: int,
    fees: FeeModel,
    slippage: Decimal,
    initial: Decimal,
    warm: int = 100,
    min_trades: int = 30,
) -> WalkForward:
    grid = combos(GRIDS[key])
    wf = WalkForward(key, market.symbol, resolution)
    curves: list[list[float]] = []
    bh_curves: list[list[float]] = []
    is_returns: list[float] = []
    start = warm
    while start + train + test <= len(series):
        tr = series[start : start + train]
        te = series[start + train : start + train + test]
        tr_warm = series[max(0, start - warm) : start]
        te_warm = series[max(0, start + train - warm) : start + train]
        best, best_score, best_ret = grid[0], float("-inf"), 0.0
        for params in grid:
            r = await _run(key, params, market, resolution, tr, tr_warm, fees, slippage, initial)
            score = _objective(r["metrics"])
            if score > best_score:
                best, best_score, best_ret = params, score, float(r["metrics"]["return_pct"])
        r = await _run(key, best, market, resolution, te, te_warm, fees, slippage, initial)
        m = r["metrics"]
        curves.append([p["equity"] for p in r["equity_curve"]])
        bh_curves.append([p["buy_hold"] for p in r["equity_curve"]])
        is_returns.append(best_ret)
        wf.folds.append(
            Fold(
                (tr[0].ts.date().isoformat(), tr[-1].ts.date().isoformat()),
                (te[0].ts.date().isoformat(), te[-1].ts.date().isoformat()),
                best,
                round(best_ret, 3),
                float(m["return_pct"]),
                float(m["max_drawdown_pct"]),
                int(m["trades"]),
                float(m["buy_hold_return_pct"]),
                float(m["buy_hold_max_drawdown_pct"]),
            )
        )
        wf.chosen = best
        start += test
    if not wf.folds:
        wf.verdict = "not enough data for one train + test window"
        return wf
    wf.oos_return_pct, wf.oos_max_dd_pct = (round(x, 3) for x in _stitch(curves))
    wf.bh_return_pct, wf.bh_max_dd_pct = (round(x, 3) for x in _stitch(bh_curves))
    wf.oos_trades = sum(f.oos_trades for f in wf.folds)
    wf.is_return_pct = round(sum(is_returns) / len(is_returns), 3)
    reasons = []
    if wf.oos_trades < min_trades:
        reasons.append(f"only {wf.oos_trades} OOS trades (< {min_trades})")
    if wf.oos_return_pct <= 0:
        reasons.append("lost money out of sample (holding cash was better)")
    if wf.oos_max_dd_pct < wf.bh_max_dd_pct:
        reasons.append("deeper drawdown than buy-and-hold")
    wf.survives = not reasons
    wf.verdict = "SURVIVES" if wf.survives else "; ".join(reasons)
    return wf
