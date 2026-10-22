"""Strategy presets from docs/research.md (walk-forward, out-of-sample).

`validated` is True only for configurations that passed every bar in docs/research.md. On the data
available on 2026-10-22 none did, so every preset here is an experiment, not a recommendation.
"""

from __future__ import annotations

from typing import Any

PRESETS: list[dict[str, Any]] = [
    {
        "key": "shock_reversal",
        "validated": False,
        "strategy": "rules",
        "resolution": "5m",
        "title_fa": "برگشت بعد از ریزش تند",
        "spec": {
            "entry": [{"kind": "drop_from_high", "pct": 10, "minutes": 30}],
            "position_size_pct": 10,
            "take_profit_pct": 1,
            "stop_loss_pct": 5,
            "cooldown_candles": 6,
        },
        "note_fa": (
            "اگر قیمت در ۳۰ دقیقه حداقل ۱۰٪ از سقفش بریزد، خلاف جهت (خرید) وارد می‌شود و با ۱٪ سود می‌فروشد. "
            "جهت دیگر (فروش استقراضی بعد از جهش) در بازار اسپات ممکن نیست. حد ضرر ۵٪ برای امنیت. (آزمایشی)"
        ),
        "evidence": "user idea, 2026-10-23; not walk-forward tested",
    },
    {
        "key": "dip3_tp5",
        "validated": False,
        "strategy": "rules",
        "resolution": "1h",
        "title_fa": "خرید پله‌ای در افت ۳٪",
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


def templates() -> list[dict[str, Any]]:
    """Rules presets as starting points for the visual builder (symbol left to the user)."""
    return [
        {
            "key": p["key"],
            "title_fa": p["title_fa"],
            "note_fa": p["note_fa"],
            "validated": p["validated"],
            "spec": {**p["spec"], "resolution": p["resolution"], "name": p["title_fa"]},
        }
        for p in PRESETS
        if p["strategy"] == "rules"
    ]


def spec_for(key: str, symbol: str) -> dict[str, Any]:
    """A full StrategySpec dict for a rules preset on `symbol`."""
    p = preset(key)
    return {**p["spec"], "symbol": symbol, "resolution": p["resolution"], "name": key}
