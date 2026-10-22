"""Triple-barrier labels: what *would* have happened to a candidate, with realistic costs.

For a candidate decided at the close of candle t, entry is at the open of candle t+1 (plus slippage).
Then, candle by candle: the stop is hit if the low reaches it (gaps fill at the open, worse than the
stop), the take-profit if the high trades through it; if both happen inside one candle we assume the
stop came first (pessimistic). After `max_bars` candles the position is closed at the close.

The label is 1 when the trade's return after fees and slippage is positive. These labels train the
meta-labeler (model.py) and score backtests of the setups themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from zirak.agent.features import WARMUP_BARS, feature_frame, implied_closes, row_features
from zirak.agent.setups import Candidate, SetupParams, scan
from zirak.models import Candle


@dataclass(frozen=True)
class Costs:
    """Fractions (0.0025 = 0.25 %)."""

    taker: float
    maker: float
    slippage: float  # per marketable fill

    def round_trip_pct(self) -> float:
        """Pessimistic round trip in %: taker in, taker out, slippage twice."""
        return (2 * self.taker + 2 * self.slippage) * 100


@dataclass(frozen=True)
class Outcome:
    exit_kind: str  # "tp" | "sl" | "time"
    bars: int
    net_ret_pct: float

    @property
    def win(self) -> int:
        return 1 if self.net_ret_pct > 0 else 0


def triple_barrier(
    df: pd.DataFrame, i: int, tp_pct: float, sl_pct: float, max_bars: int, costs: Costs
) -> Outcome | None:
    """None when there aren't enough future candles to know the outcome."""
    n = len(df)
    if i + 1 >= n:
        return None
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    entry = o[i + 1] * (1 + costs.slippage)
    cost_in = entry * (1 + costs.taker)
    tp, sl = entry * (1 + tp_pct / 100), entry * (1 - sl_pct / 100)
    last = min(n - 1, i + max_bars)
    if i + max_bars >= n:
        return None
    for j in range(i + 1, last + 1):
        if lo[j] <= sl:
            px = min(sl, o[j]) * (1 - costs.slippage)  # a gap through the stop fills at the (worse) open
            return Outcome("sl", j - i, (px * (1 - costs.taker) / cost_in - 1) * 100)
        if h[j] > tp:
            return Outcome("tp", j - i, (tp * (1 - costs.maker) / cost_in - 1) * 100)
    px = c[last] * (1 - costs.slippage)
    return Outcome("time", last - i, (px * (1 - costs.taker) / cost_in - 1) * 100)


def build_dataset(
    series: dict[str, list[Candle]],
    costs: Costs,
    min_tp_pct: float,
    params: dict[str, SetupParams] | None = None,
) -> pd.DataFrame:
    """Every labelled candidate in `series` (symbol -> candles), oldest first, one row per candidate."""
    rows: list[dict[str, object]] = []
    for symbol, candles in series.items():
        df = feature_frame(candles, implied_closes(series, symbol))
        for i in range(WARMUP_BARS, len(df) - 1):
            for cand in scan(df, i, symbol, min_tp_pct, params):
                out = triple_barrier(df, i, cand.tp_pct, cand.sl_pct, cand.max_bars, costs)
                if out is None:
                    continue
                rows.append(_row(cand, row_features(df, i), out))
    data = pd.DataFrame(rows)
    return data.sort_values("ts", kind="stable").reset_index(drop=True) if not data.empty else data


def _row(cand: Candidate, feats: dict[str, float], out: Outcome) -> dict[str, object]:
    return {
        "ts": cand.ts,
        "symbol": cand.symbol,
        "setup": cand.setup,
        "tp_pct": cand.tp_pct,
        "sl_pct": cand.sl_pct,
        **feats,
        "label": out.win,
        "net_ret_pct": out.net_ret_pct,
        "exit_kind": out.exit_kind,
        "bars": out.bars,
    }
