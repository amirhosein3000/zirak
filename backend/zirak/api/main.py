"""FastAPI app: market data, Persian brief, strategy builder, backtests, paper bot and kill switch."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from zirak import __version__
from zirak.backtest.engine import BacktestSetup, run_backtest_async, save_report
from zirak.config import Settings, load_settings
from zirak.data.source import build_replay, load_series
from zirak.engine.risk import RiskConfig
from zirak.engine.runner import BotRunner, RunnerError
from zirak.exchange.guard import live_blockers
from zirak.fees import FeeModel
from zirak.llm.brief import compute_facts, market_brief
from zirak.llm.builder import build_strategy
from zirak.llm.explain import explain_entry
from zirak.llm.provider import build_llm
from zirak.markets import ASSET_NAMES_FA, market_name_fa
from zirak.strategy.base import Strategy
from zirak.strategy.registry import build_strategy as make_strategy
from zirak.strategy.registry import catalog
from zirak.strategy.spec import RuleStrategy, StrategySpec


class ParseIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    symbol: str | None = None


class RunIn(BaseModel):
    symbol: str = "BTCTMN"
    resolution: str = "1h"
    strategy: str = "rules"  # a registry key, or "rules" with `spec`
    params: dict[str, Any] = Field(default_factory=dict)
    spec: dict[str, Any] | None = None
    risk: dict[str, Any] = Field(default_factory=dict)
    initial_quote: Decimal | None = None
    speed_s: float = Field(1.0, ge=0.05, le=30)


class ExplainIn(BaseModel):
    entry: dict[str, Any]


class State:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.replay, self.data_label = build_replay(settings)
        self.runner = BotRunner(settings, self.replay)
        self.llm = build_llm(settings)
        self.reports_dir = settings.data_dir / "reports"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    state = State(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await state.runner.stop()

    app = FastAPI(title="Zirak API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
    )
    app.state.zirak = state

    # ---- meta ------------------------------------------------------------------------------------
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "data_source": settings.data_source,
            "data": state.data_label,
            "llm": state.llm.name,
            "live_trading": not live_blockers(settings),
            "live_blockers": live_blockers(settings),
            "kill_engaged": state.runner.kill_engaged,
        }

    @app.get("/api/markets")
    async def markets() -> list[dict[str, Any]]:
        out = []
        for symbol, res, count in state.replay.available():
            if res != "1h" or symbol not in settings.markets:
                continue
            m = state.replay.markets[symbol]
            vis = state.replay.visible(symbol, "1h")
            last, prev = (vis[-1].close, vis[-25].close) if len(vis) > 25 else (None, None)
            out.append(
                {
                    "symbol": symbol,
                    "base": m.base,
                    "quote": m.quote,
                    "name_fa": market_name_fa(m),
                    "base_fa": ASSET_NAMES_FA.get(m.base, m.base),
                    "quote_fa": ASSET_NAMES_FA.get(m.quote, m.quote),
                    "price": str(last) if last else None,
                    "change_24h_pct": float((last / prev - 1) * 100) if last and prev else None,
                    "candles": count,
                    "verified": m.verified,
                }
            )
        return out

    @app.get("/api/markets/{symbol}/candles")
    async def candles(symbol: str, resolution: str = "1h", limit: int = 200) -> list[dict[str, Any]]:
        vis = state.replay.visible(symbol, resolution)
        if not vis:
            raise HTTPException(404, f"no {resolution} data for {symbol}")
        return [c.to_dict() for c in vis[-min(limit, 1000) :]]

    @app.get("/api/markets/{symbol}/brief")
    async def brief(symbol: str) -> dict[str, Any]:
        market = state.replay.markets.get(symbol)
        vis = state.replay.visible(symbol, "1h")
        if market is None or not vis:
            raise HTTPException(404, f"no data for {symbol}")
        book = await state.replay.get_order_book(symbol)
        facts = compute_facts(market, vis, book)
        text, source = await market_brief(state.llm, market, facts)
        return {
            "symbol": symbol,
            "brief_fa": text,
            "source": source,
            "facts": facts.to_dict(),
            "as_of": vis[-1].ts.isoformat(),
            "data": state.data_label,
        }

    # ---- strategies --------------------------------------------------------------------------------
    @app.get("/api/strategies")
    async def strategies() -> list[dict[str, Any]]:
        return catalog()

    @app.post("/api/strategy/parse")
    async def parse(body: ParseIn) -> dict[str, Any]:
        result = await build_strategy(state.llm, body.text, body.symbol)
        return result.to_dict()

    def strategy_and_risk(body: RunIn) -> tuple[Strategy, RiskConfig, str, str]:
        try:
            if body.strategy == "rules":
                if body.spec is None:
                    raise HTTPException(422, "spec is required for strategy=rules")
                spec = StrategySpec.model_validate(body.spec)
                strat: Strategy = RuleStrategy(spec)
                risk = RiskConfig.from_dict(
                    {
                        "stop_loss_pct": spec.stop_loss_pct,
                        "take_profit_pct": spec.take_profit_pct,
                        "cooldown_candles": spec.cooldown_candles,
                        "max_position_pct": max(80.0, spec.position_size_pct),
                        **body.risk,
                    }
                )
                return strat, risk, spec.symbol, spec.resolution
            strat = make_strategy(body.strategy, body.params)
            return strat, RiskConfig.from_dict(body.risk), body.symbol, body.resolution
        except (ValidationError, KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, str(e)) from e

    # ---- backtests ---------------------------------------------------------------------------------
    @app.post("/api/backtest")
    async def backtest(body: RunIn) -> dict[str, Any]:
        strat, risk, symbol, resolution = strategy_and_risk(body)
        market = state.replay.markets.get(symbol)
        if market is None:
            raise HTTPException(404, f"unknown market {symbol}")
        try:
            series = load_series(state.replay, symbol, resolution)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        initial = body.initial_quote or (
            settings.paper_start_tmn if market.quote == "TMN" else settings.paper_start_usdt
        )
        setup = BacktestSetup(
            market=market,
            resolution=resolution,
            strategy=strat,
            risk=risk,
            fees=FeeModel(settings.fee_maker, settings.fee_taker),
            slippage_bps=settings.slippage_bps,
            initial_quote=initial,
            participation=settings.fill_participation,
            meta={"data": state.data_label, "spec": body.spec},
        )
        report = await run_backtest_async(series, setup)
        save_report(report, state.reports_dir)
        return report

    @app.get("/api/backtests/{report_id}")
    async def get_report(report_id: str) -> dict[str, Any]:
        path = state.reports_dir / f"{report_id}.json"
        if not report_id.isalnum() or not path.exists():
            raise HTTPException(404, "report not found")
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    # ---- paper bot & kill switch ---------------------------------------------------------------------
    @app.post("/api/bot/start")
    async def bot_start(body: RunIn) -> dict[str, Any]:
        strat, risk, symbol, resolution = strategy_and_risk(body)
        try:
            await state.runner.start(strat, risk, symbol, resolution, body.initial_quote, body.speed_s)
        except (RunnerError, KeyError) as e:
            raise HTTPException(409, str(e)) from e
        return await state.runner.status()

    @app.get("/api/bot/status")
    async def bot_status() -> dict[str, Any]:
        return await state.runner.status()

    @app.post("/api/bot/stop")
    async def bot_stop() -> dict[str, Any]:
        await state.runner.stop()
        return await state.runner.status()

    @app.post("/api/kill")
    async def kill() -> dict[str, Any]:
        canceled = await state.runner.kill("api")
        return {"killed": True, "canceled_orders": [o.id for o in canceled], **(await state.runner.status())}

    @app.post("/api/kill/reset")
    async def kill_reset() -> dict[str, Any]:
        if state.runner.running:
            raise HTTPException(409, "bot is still running")
        state.runner.reset_kill()
        return await state.runner.status()

    @app.get("/api/bot/log/{entry_id}/explain")
    async def explain(entry_id: int) -> dict[str, Any]:
        bot = state.runner.bot
        if bot is None or not 1 <= entry_id <= len(bot.log):
            raise HTTPException(404, "log entry not found")
        entry = bot.log[entry_id - 1]
        if entry.explanation_fa is None:
            entry.explanation_fa, _ = await explain_entry(state.llm, entry.to_dict())
        return {"id": entry_id, "explanation_fa": entry.explanation_fa}

    @app.post("/api/explain")
    async def explain_any(body: ExplainIn) -> dict[str, Any]:
        """Explain a trade from a backtest report (the client sends the logged entry)."""
        try:
            text, source = await explain_entry(state.llm, body.entry)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, f"bad entry: {e}") from e
        return {"explanation_fa": text, "source": source}

    return app


app = create_app()
