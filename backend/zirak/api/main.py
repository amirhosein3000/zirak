"""FastAPI app: market data, Persian brief, strategy builder, backtests, paper bot and kill switch."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from zirak import __version__
from zirak.backtest.engine import BacktestSetup, run_backtest, save_report
from zirak.backtest.insights import Period, risk_shield, select_period, unprotected, zirak_score
from zirak.config import Settings, load_settings
from zirak.data.source import build_replay, load_series
from zirak.engine.risk import RiskConfig
from zirak.engine.runner import BotRunner, RunnerError
from zirak.exchange.guard import live_blockers
from zirak.exchange.wallex import WallexAPIError, WallexClient
from zirak.fees import FeeModel
from zirak.i18n import fa_num, fa_pct
from zirak.llm.brief import compute_facts, market_brief
from zirak.llm.builder import build_strategy
from zirak.llm.explain import explain_entry
from zirak.llm.provider import build_llm
from zirak.markets import ASSET_NAMES_FA, market_name_fa
from zirak.models import RESOLUTION_SECONDS, Candle, Market, OrderBook, resolution_delta, utcnow
from zirak.strategy.base import Strategy
from zirak.strategy.registry import DEFAULT_PARAMS, STRATEGIES, catalog
from zirak.strategy.registry import build_strategy as make_strategy
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
    period: str = "90d"  # 30d | 90d | 180d | 365d | all | crash


# The user must type this exact sentence to start a real-money bot.
LIVE_CONFIRM_PHRASE = "می‌دانم با پول واقعی معامله می‌کنم"


class LiveStartIn(RunIn):
    confirm: str = ""


class ExplainIn(BaseModel):
    entry: dict[str, Any]


class State:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.replay, self.replay_label = build_replay(settings)
        self.data_label = self.replay_label
        #: live public market data from Wallex when DATA_SOURCE=wallex (paper trading stays paper)
        self.live = WallexClient(settings) if settings.data_source == "wallex" else None
        if self.live is not None:
            self.data_label = "live"
        self.runner = BotRunner(settings, self.replay, self.live)
        self.llm = build_llm(settings)
        self.reports_dir = settings.data_dir / "reports"
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _cached(self, key: str, ttl: float, fn: Callable[[], Awaitable[Any]]) -> Any:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        try:
            value = await fn()
        except (httpx.HTTPError, WallexAPIError) as e:
            raise HTTPException(
                503, "اتصال به داده‌های زندهٔ والکس برقرار نشد؛ کمی بعد دوباره تلاش کنید."
            ) from e
        self._cache[key] = (time.monotonic(), value)
        return value

    async def market(self, symbol: str) -> Market | None:
        if self.live is None:
            return self.replay.markets.get(symbol)
        live = self.live
        markets: dict[str, Market] = await self._cached("markets", 3600, lambda: _as_dict(live.get_markets()))
        return markets.get(symbol)

    async def candles(self, symbol: str, resolution: str, limit: int) -> list[Candle]:
        if self.live is None:
            return self.replay.visible(symbol, resolution)[-limit:]
        live, step = self.live, resolution_delta(resolution)
        series: list[Candle] = await self._cached(
            f"c:{symbol}:{resolution}:{limit}",
            20,
            lambda: live.get_candles(symbol, resolution, utcnow() - step * int(limit * 1.3 + 5), utcnow()),
        )
        return series[-limit:]

    async def book(self, symbol: str) -> OrderBook:
        if self.live is None:
            return await self.replay.get_order_book(symbol)
        live = self.live
        book: OrderBook = await self._cached(f"b:{symbol}", 5, lambda: live.get_order_book(symbol))
        return book


async def _as_dict(coro: Awaitable[list[Market]]) -> dict[str, Market]:
    return {m.symbol: m for m in await coro}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    state = State(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await state.runner.stop()
        if state.live is not None:
            await state.live.close()

    app = FastAPI(title="Zirak API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",  # any local dev port
        allow_methods=["*"],
        allow_headers=["*"],
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
        for symbol in settings.markets:
            m = await state.market(symbol)
            series = await state.candles(symbol, "1h", 25)
            if m is None or not series:
                continue
            last, prev = series[-1].close, series[0].close if len(series) >= 25 else None
            out.append(
                {
                    "symbol": symbol,
                    "base": m.base,
                    "quote": m.quote,
                    "name_fa": market_name_fa(m),
                    "base_fa": ASSET_NAMES_FA.get(m.base, m.base),
                    "quote_fa": ASSET_NAMES_FA.get(m.quote, m.quote),
                    "price": str(last),
                    "change_24h_pct": float((last / prev - 1) * 100) if prev else None,
                    "candles": len(state.replay.series(symbol, "1h")),
                    "verified": m.verified,
                }
            )
        return out

    @app.get("/api/markets/{symbol}/candles")
    async def candles(symbol: str, resolution: str = "1h", limit: int = 200) -> list[dict[str, Any]]:
        if resolution not in RESOLUTION_SECONDS:
            raise HTTPException(422, f"unknown resolution {resolution}")
        series = await state.candles(symbol, resolution, min(limit, 1000))
        if not series:
            raise HTTPException(404, f"no {resolution} data for {symbol}")
        return [c.to_dict() for c in series]

    @app.get("/api/markets/{symbol}/brief")
    async def brief(symbol: str) -> dict[str, Any]:
        market = await state.market(symbol)
        series = await state.candles(symbol, "1h", 300)
        if market is None or not series:
            raise HTTPException(404, f"no data for {symbol}")
        book = await state.book(symbol)
        facts = compute_facts(market, series, book)
        text, source = await market_brief(state.llm, market, facts)
        return {
            "symbol": symbol,
            "brief_fa": text,
            "source": source,
            "facts": facts.to_dict(),
            "as_of": series[-1].ts.isoformat(),
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
    def market_series(symbol: str, resolution: str) -> tuple[Market, list[Candle]]:
        market = state.replay.markets.get(symbol)
        if market is None:
            raise HTTPException(404, f"unknown market {symbol}")
        try:
            return market, load_series(state.replay, symbol, resolution)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e

    async def run_one(
        strat: Strategy, risk: RiskConfig, market: Market, resolution: str, period: Period, body: RunIn
    ) -> dict[str, Any]:
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
            meta={"data": state.replay_label, "spec": body.spec},
        )
        # CPU-bound: run in a worker thread so the paper bot's loop keeps ticking.
        report: dict[str, Any] = await asyncio.to_thread(run_backtest, period.candles, setup, period.warmup)
        report["period"] = period.to_dict()
        return report

    @app.post("/api/backtest")
    async def backtest(body: RunIn) -> dict[str, Any]:
        strat, risk, symbol, resolution = strategy_and_risk(body)
        market, series = market_series(symbol, resolution)
        period = select_period(series, body.period, resolution)
        report = await run_one(strat, risk, market, resolution, period, body)
        naked_strat = strategy_and_risk(body)[0]  # fresh instance: strategies keep state
        naked = await run_one(naked_strat, unprotected(risk), market, resolution, period, body)
        report["score"] = zirak_score(report["metrics"])
        report["shield"] = risk_shield(report, naked, market.quote)
        save_report(report, state.reports_dir)
        return report

    @app.post("/api/duel")
    async def duel(body: RunIn) -> dict[str, Any]:
        """Your strategy vs the baselines vs an emotional trader vs buy-and-hold, same market and period."""
        _, _, symbol, resolution = strategy_and_risk(body)
        market, series = market_series(symbol, resolution)
        period = select_period(series, body.period, resolution)
        entrants: list[tuple[str, bool, RunIn]] = []
        if body.strategy == "rules" or body.strategy not in DEFAULT_PARAMS:
            entrants.append(("yours", True, body))
        for key in [*DEFAULT_PARAMS, "fomo"]:
            params = body.params if key == body.strategy else DEFAULT_PARAMS.get(key, {})
            entrants.append(
                (
                    key,
                    key == body.strategy,
                    body.model_copy(
                        update={
                            "strategy": key,
                            "params": params,
                            "spec": None,
                            "symbol": symbol,
                            "resolution": resolution,
                        }
                    ),
                )
            )
        rows: list[dict[str, Any]] = []
        first: dict[str, Any] | None = None
        for key, mine, run in entrants:
            strat, risk, _, _ = strategy_and_risk(run)
            rep = await run_one(strat, risk, market, resolution, period, run)
            first = first or rep
            m, sc = rep["metrics"], zirak_score(rep["metrics"])
            title = "استراتژی شما" if key == "yours" else STRATEGIES[key].title_fa
            rows.append(
                {
                    "key": key,
                    "title_fa": title,
                    "mine": mine,
                    "return_pct": m["return_pct"],
                    "max_drawdown_pct": m["max_drawdown_pct"],
                    "trades": m["trades"],
                    "win_rate_pct": m["win_rate_pct"],
                    "score": sc["score"],
                    "grade": sc["grade"],
                    "emotional": key == "fomo",
                }
            )
        assert first is not None
        fm = first["metrics"]
        bh_metrics = {
            **fm,
            "return_pct": fm["buy_hold_return_pct"],
            "max_drawdown_pct": fm["buy_hold_max_drawdown_pct"],
            "trades": 0,
            "win_rate_pct": 0.0,
        }
        bh_score = zirak_score(bh_metrics)
        rows.append(
            {
                "key": "buy_hold",
                "title_fa": "خرید و نگهداری",
                "mine": False,
                "return_pct": fm["buy_hold_return_pct"],
                "max_drawdown_pct": fm["buy_hold_max_drawdown_pct"],
                "trades": 0,
                "win_rate_pct": 0.0,
                "score": bh_score["score"],
                "grade": bh_score["grade"],
                "emotional": False,
            }
        )
        rows.sort(key=lambda r: r["score"], reverse=True)
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        mine_row = next((r for r in rows if r["mine"]), None)
        fomo_row = next(r for r in rows if r["emotional"])
        headline = (
            f"استراتژی شما رتبهٔ {fa_num(mine_row['rank'], 0)} از {fa_num(len(rows), 0)} شد."
            if mine_row
            else "مقایسهٔ استراتژی‌ها"
        )
        if mine_row:
            gap = mine_row["return_pct"] - fomo_row["return_pct"]
            headline += (
                f" نسبت به یک معامله‌گر هیجانی {fa_pct(abs(gap), 1)} {'بهتر' if gap >= 0 else 'بدتر'} عمل کرد."
            )
        return {
            "symbol": symbol,
            "resolution": resolution,
            "quote": market.quote,
            "period": period.to_dict(),
            "rows": rows,
            "headline_fa": headline,
        }

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

    # ---- live money: pre-flight checklist and guarded start ----------------------------------------
    async def preflight() -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add(key: str, ok: bool, title: str, detail: str = "", required: bool = True) -> None:
            checks.append(
                {"key": key, "ok": ok, "title_fa": title, "detail_fa": detail, "required": required}
            )

        add("live_flag", settings.live_trading, "معاملهٔ واقعی در تنظیمات روشن است (LIVE_TRADING=true)")
        add(
            "order_caps",
            bool(settings.max_order_tmn and settings.max_order_usdt),
            "سقف هر سفارش تعیین شده است",
            f"تومان: {fa_num(settings.max_order_tmn or 0, 0)} — تتر: {fa_num(settings.max_order_usdt or 0, 2)}",
        )
        add(
            "daily_loss",
            bool(settings.daily_loss_limit_pct),
            "سقف زیان روزانه تعیین شده است",
            f"{fa_pct(settings.daily_loss_limit_pct or 0, 1)} از سرمایهٔ ابتدای روز",
        )
        add("kill_switch", not state.runner.kill_engaged, "کلید توقف اضطراری آزاد و آماده است")
        add("data_source", settings.data_source == "wallex", "دادهٔ زندهٔ والکس فعال است (DATA_SOURCE=wallex)")
        add(
            "api_key",
            bool(settings.wallex_api_key),
            "کلید API والکس تنظیم شده است",
            "فقط با دسترسی معامله؛ هرگز دسترسی برداشت",
        )
        client = state.live or WallexClient(settings)
        balances: dict[str, str] = {}
        fees: dict[str, Any] = {}
        try:
            try:
                await client.get_markets()
                add("reachable", True, "اتصال به والکس برقرار است")
            except (httpx.HTTPError, WallexAPIError) as e:
                add("reachable", False, "اتصال به والکس برقرار است", type(e).__name__)
            if settings.wallex_api_key:
                try:
                    bal = await client.get_balances()
                    balances = {a: str(b.total) for a, b in bal.items() if a in ("TMN", "USDT", "BTC", "ETH")}
                    add(
                        "key_valid",
                        True,
                        "کلید API معتبر است و موجودی خوانده شد",
                        f"تومان: {fa_num(bal['TMN'].total, 0) if 'TMN' in bal else '۰'}",
                    )
                except (httpx.HTTPError, WallexAPIError) as e:
                    add("key_valid", False, "کلید API معتبر است و موجودی خوانده شد", str(e)[:120])
                try:
                    raw = await client.get_fees()
                    fees = {
                        k: {"maker": str(v[0]), "taker": str(v[1])}
                        for k, v in raw.items()
                        if k in settings.markets
                    }
                    add("fees", True, "کارمزد حساب شما از والکس خوانده شد", "", required=False)
                except (httpx.HTTPError, WallexAPIError) as e:
                    add("fees", False, "کارمزد حساب شما از والکس خوانده شد", str(e)[:120], required=False)
        finally:
            if client is not state.live:
                await client.close()
        ready = all(c["ok"] for c in checks if c["required"])
        return {
            "ready": ready,
            "checks": checks,
            "balances": balances,
            "fees": fees,
            "confirm_phrase": LIVE_CONFIRM_PHRASE,
            "max_slippage_bps": str(settings.live_max_slippage_bps),
            "order_ttl_s": settings.live_order_ttl_s,
        }

    @app.get("/api/live/preflight")
    async def live_preflight() -> dict[str, Any]:
        return await preflight()

    @app.post("/api/live/start")
    async def live_start(body: LiveStartIn) -> dict[str, Any]:
        if body.confirm.strip() != LIVE_CONFIRM_PHRASE:
            raise HTTPException(400, "برای شروع معاملهٔ واقعی، جملهٔ تأیید را دقیقاً تایپ کنید.")
        pf = await preflight()
        if not pf["ready"]:
            failed = [c["title_fa"] for c in pf["checks"] if c["required"] and not c["ok"]]
            raise HTTPException(409, "پیش‌پرواز کامل نیست: " + "، ".join(failed))
        strat, risk, symbol, resolution = strategy_and_risk(body)
        try:
            await state.runner.start(strat, risk, symbol, resolution, real=True)
        except (RunnerError, KeyError) as e:
            raise HTTPException(409, str(e)) from e
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
