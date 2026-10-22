"""Optional feature modules, each behind the `MODULES` flag (comma-separated names; default: all).

Every module is one file in this package that exposes `router` (a FastAPI APIRouter mounted under
`/api/m/<name>`) and pure functions that work offline (MOCK_LLM, paper/replay data). Modules only
read market data through the API's `State` and never place orders themselves.

To remove a module: delete its file, its test, its entry in `AVAILABLE` and its UI card.
"""

from __future__ import annotations

import importlib

from fastapi import FastAPI

from zirak.config import Settings

#: name -> one-line description (English, for /api/modules and docs)
AVAILABLE: dict[str, str] = {
    "regime": "market regime detector (trending / ranging / volatile) + regime-gated strategies",
    "orderbook": "order-book intelligence: spread, depth, imbalance, walls, fair Toman price of USDT",
    "news": "crypto news with Persian summary and sentiment; optional size reduction on bad news",
    "portfolio": "target allocation with threshold rebalancing, backtested, with Persian explanations",
    "alerts": "price / RSI / PnL alerts, in-app plus optional Telegram or Bale bot",
    "coach": "AI coach: reviews recent trades and gives Persian feedback",
    "competition": "headless multi-strategy runner with strict limits and a live performance file",
}


def enabled(settings: Settings) -> list[str]:
    return [m for m in settings.modules if m in AVAILABLE]


def mount(app: FastAPI, settings: Settings) -> list[str]:
    """Import and mount every enabled module's router. Returns the mounted names."""
    mounted: list[str] = []
    for name in enabled(settings):
        try:
            mod = importlib.import_module(f"zirak.modules.{name}")
        except ModuleNotFoundError as e:
            if e.name == f"zirak.modules.{name}":
                continue  # the module's file was deleted: treat it as switched off
            raise
        app.include_router(mod.router, prefix=f"/api/m/{name}", tags=[name])
        mounted.append(name)
    return mounted
