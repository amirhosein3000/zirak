"""Strategy registry: key -> class. Add new strategies here."""

from __future__ import annotations

from typing import Any

from zirak.strategy.base import Strategy
from zirak.strategy.baseline import Dca, EmaCross, EmotionalTrader, Grid, RsiReversion
from zirak.strategy.spec import RuleStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    cls.key: cls for cls in (EmaCross, RsiReversion, Grid, Dca, RuleStrategy, EmotionalTrader)
}

# Default parameters shown in the UI for the baseline strategies.
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "ema_cross": {"fast": 12, "slow": 26, "size_pct": 50},
    "rsi_reversion": {"period": 14, "low": 30, "high": 65, "size_pct": 40},
    "grid": {"levels": 8, "range_pct": 8},
    "dca": {"every": 24, "size_pct": 5, "take_profit_pct": 6, "max_entries": 10},
}


def build_strategy(key: str, params: dict[str, Any] | None = None) -> Strategy:
    if key not in STRATEGIES:
        raise KeyError(f"unknown strategy {key!r}; known: {sorted(STRATEGIES)}")
    return STRATEGIES[key](**(params or {}))


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": k,
            "title_fa": STRATEGIES[k].title_fa,
            "description_fa": STRATEGIES[k].description_fa,
            "params": DEFAULT_PARAMS[k],
        }
        for k in DEFAULT_PARAMS
    ]
