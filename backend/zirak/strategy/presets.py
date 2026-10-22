"""Strategy presets from docs/research.md (walk-forward, out-of-sample).

`validated` is True only for configurations that passed every bar in docs/research.md. On the data
available on 2026-10-22 none did, so every preset here is an experiment, not a recommendation.
"""

from __future__ import annotations

from typing import Any

PRESETS: list[dict[str, Any]] = [
    {
        "key": "dip3_tp5",
        "validated": False,
        "strategy": "rules",
        "resolution": "1h",
        "spec": {
            "entry": [{"kind": "drop_from_high", "pct": 3, "lookback": 24}],
            "position_size_pct": 10,
            "take_profit_pct": 5,
            "stop_loss_pct": 5,
        },
        "note_fa": "خرید پله‌ای کوچک در افت‌های ۳٪ با حد سود ۵٪ و حد ضرر ۵٪ (آزمایشی؛ شواهد کافی ندارد)",
        "evidence": "OOS 1h: +1.0% BTCTMN, +1.1% ETHTMN, +0.6% USDTTMN, +0.2% BTCUSDT, -0.6% ETHUSDT; 19 trades",
    },
    {
        "key": "rsi_calm",
        "validated": False,
        "strategy": "rsi_reversion",
        "resolution": "1h",
        "params": {"period": 14, "low": 30, "high": 65, "size_pct": 40},
        "note_fa": "خرید در اشباع فروش و فروش در برگشت، با حد ضرر ۵٪ (آزمایشی؛ شواهد کافی ندارد)",
        "evidence": "OOS 1h: mixed (-3.7% to +0.5%), 2-6 trades per market",
    },
]


def preset(key: str) -> dict[str, Any]:
    for p in PRESETS:
        if p["key"] == key:
            return p
    raise KeyError(key)


def spec_for(key: str, symbol: str) -> dict[str, Any]:
    """A full StrategySpec dict for a rules preset on `symbol`."""
    p = preset(key)
    return {**p["spec"], "symbol": symbol, "resolution": p["resolution"], "name": key}
