"""Optional modules (zirak/modules): pure logic plus their API routes, fully offline."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from fastapi.testclient import TestClient

from zirak.api.main import create_app
from zirak.config import SAMPLE_DATA_DIR, Settings
from zirak.indicators import candles_to_df
from zirak.llm.provider import MockLLM
from zirak.models import BookLevel, Candle, Market, OrderBook, Side
from zirak.modules import news, orderbook, regime

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def settings(tmp_path: Path, **kw: object) -> Settings:
    s = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "none.sqlite",
        kill_file=tmp_path / "KILL",
        replay_dir=SAMPLE_DATA_DIR,
    )
    return replace(s, **kw)  # type: ignore[arg-type]


def series(closes: list[float]) -> list[Candle]:
    out = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        hi, lo = max(c, prev) * 1.001, min(c, prev) * 0.999
        out.append(
            Candle(T0 + timedelta(hours=i), D(str(prev)), D(f"{hi:.4f}"), D(f"{lo:.4f}"), D(str(c)), D("10"))
        )
    return out


# ---- regime ------------------------------------------------------------------------------------
def test_regime_trend_range_and_volatile() -> None:
    up = [100 * 1.004**i for i in range(150)]
    assert regime.classify(candles_to_df(series(up))).regime == "trending_up"
    down = [100 * 0.996**i for i in range(150)]
    assert regime.classify(candles_to_df(series(down))).regime == "trending_down"
    chop = [100 + (1 if i % 2 else -1) * 0.5 for i in range(150)]
    r = regime.classify(candles_to_df(series(chop)))
    assert r.regime == "ranging" and r.label_fa and "rsi_reversion" in r.suits
    rng = np.random.default_rng(1)
    calm = [float(x) for x in 100 + np.cumsum(rng.normal(0, 0.05, 140))]
    wild = [calm[-1] * (1 + (0.04 if i % 2 else -0.04)) for i in range(10)]
    assert regime.classify(candles_to_df(series(calm + wild))).regime == "volatile"


def test_regime_gate_blocks_buys_but_never_sells() -> None:
    from zirak.markets import DEFAULT_MARKETS
    from zirak.strategy.base import Frame, Signal, Strategy, StrategyContext

    class Both(Strategy):
        key = "both"

        def on_candle(self, ctx: StrategyContext) -> list[Signal]:
            return [Signal(Side.BUY, D("10"), "b", "b"), Signal(Side.SELL, D("100"), "s", "s")]

    down = series([100 * 0.996**i for i in range(150)])
    ctx = StrategyContext(
        "BTCTMN",
        DEFAULT_MARKETS["BTCTMN"],
        "1h",
        down[-1].ts,
        Frame.from_dataframe(candles_to_df(down)),
        D(1),
        D(100),
        1,
        D(1000),
        D(1000),
    )
    gated = regime.RegimeGated(Both(), ["trending_up"])
    assert [s.side for s in gated.on_candle(ctx)] == [Side.SELL]
    assert [s.side for s in regime.RegimeGated(Both(), ["trending_down"]).on_candle(ctx)] == [
        Side.BUY,
        Side.SELL,
    ]
    assert "trending_up" in gated.describe()["regimes"]


# ---- order book ---------------------------------------------------------------------------------
def test_orderbook_stats_and_walls() -> None:
    bids = [BookLevel(D("99.9") - D("0.05") * i, D("1")) for i in range(10)] + [BookLevel(D("98"), D("20"))]
    asks = [BookLevel(D("100.1") + D("0.2") * i, D("1")) for i in range(10)]
    st = orderbook.analyse(OrderBook("X", T0, bids, asks))
    assert st.mid == 100 and round(st.spread_pct, 3) == 0.2
    assert st.imbalance_pct > 0
    assert st.walls and st.walls[0].side == "bid" and st.walls[0].price == 98
    assert "دیوار خرید" in st.summary_fa


def test_fair_usdt_premium() -> None:
    f = orderbook.fair_usdt(
        {
            "USDTTMN": 101_000,
            "BTCTMN": 100_000 * 60_000,
            "BTCUSDT": 60_000,
            "ETHTMN": 3000 * 100_000,
            "ETHUSDT": 3000,
        }
    )
    assert f.fair == 100_000 and f.premium_pct == 1.0 and "گران‌تر" in f.summary_fa
    assert orderbook.fair_usdt({"USDTTMN": 1}).fair is None


# ---- news ---------------------------------------------------------------------------------------
def test_news_scoring_and_assets() -> None:
    assert news.score_text("Bitcoin rally hits record high") > 0
    assert news.score_text("Exchange hacked, prices crash") < 0
    assert news.score_text("سقوط بازار و هشدار") < 0
    assert news.assets_in("Ethereum and bitcoin") == ["BTC", "ETH"]
    assert news.size_factor_for(-0.5) == 0.5 and news.size_factor_for(0.1) == 1.0


def test_news_rss_parsing_without_network(tmp_path: Path) -> None:
    rss = """<?xml version="1.0"?><rss><channel>
      <item><title>Bitcoin surges to record</title><link>https://ex/1</link>
        <pubDate>Wed, 21 Oct 2026 10:00:00 GMT</pubDate></item>
      <item><title>Exchange hacked</title><link>https://ex/2</link></item>
    </channel></rss>"""
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Ether slump deepens</title>
      <link href="https://ex/3"/><updated>2026-10-21T09:00:00Z</updated></entry></feed>"""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=rss if "rss" in str(r.url) else atom))
    s = settings(tmp_path, news_source="rss", news_rss_urls=["https://a.test/rss", "https://b.test/atom"])
    items = asyncio.run(news.fetch_news(s, transport))
    assert {i.title for i in items} == {"Bitcoin surges to record", "Exchange hacked", "Ether slump deepens"}
    sent = asyncio.run(news.analyse(items, MockLLM(), None, "rss"))
    assert sent.negative == 2 and sent.positive == 1 and "توصیهٔ مالی نیست" in sent.summary_fa


def test_negative_news_only_shrinks_buys() -> None:
    from tests.test_risk import BUY, rm, view

    r = rm_market = rm(regime_market())
    r.size_factor = D("0.5")
    d = r.review(BUY, view())
    full = rm(rm_market.market).review(BUY, view())
    assert d.approved and d.qty < full.qty
    r.size_factor = D("3")  # nonsense input is clamped: never enlarges
    assert r.review(BUY, view()).qty == full.qty


def regime_market() -> Market:  # the test_risk market fixture, built directly
    return Market("TESTUSDT", "TST", "USDT", D("0.01"), D("0.001"), D("0.001"), D("5"))


# ---- API ---------------------------------------------------------------------------------------
def test_module_routes_and_flags(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as c:
        mods = c.get("/api/modules").json()
        assert "regime" in mods["enabled"] and "competition" in mods["available"]
        r = c.get("/api/m/regime/BTCTMN").json()
        assert r["regime"] in regime.REGIMES
        ob = c.get("/api/m/orderbook/BTCTMN").json()
        assert ob["synthetic"] and ob["summary_fa"]
        assert "summary_fa" in c.get("/api/m/orderbook/fair-usdt").json()
        n = c.get("/api/m/news", params={"asset": "BTC"}).json()
        assert n["items"] and n["source"] == "mock"
        assert c.post("/api/m/news/apply").json()["applied"] is False  # NEWS_RISK off by default
        g = c.post(
            "/api/m/regime/backtest", json={"strategy": "ema_cross", "allowed": ["trending_up"]}
        ).json()
        assert "plain" in g and "gated" in g
    with TestClient(create_app(settings(tmp_path, modules=["regime"]))) as c:
        assert c.get("/api/modules").json()["enabled"] == ["regime"]
        assert c.get("/api/m/news").status_code == 404  # switched off


# ---- portfolio ----------------------------------------------------------------------------------
def test_portfolio_rebalances_honestly() -> None:
    from zirak.markets import DEFAULT_MARKETS
    from zirak.modules import portfolio

    btc = series([3_000_000_000 * (1.01**i) for i in range(60)])  # BTC rallies +80 %
    usdt = series([100_000.0] * 60)
    markets = {m: DEFAULT_MARKETS[m] for m in ("BTCTMN", "USDTTMN")}
    targets = {"TMN": D(0), "USDT": D(50), "BTC": D(50)}
    r = portfolio.backtest({"BTC": btc, "USDT": usdt}, targets, markets, D("100000000"), D("0.0025"), D("5"))
    assert r["rebalances"], "a +80 % rally must trigger rebalancing"
    first = r["rebalances"][0]
    assert first["trades"][0]["asset"] == "BTC" and first["trades"][0]["side"] == "sell"  # sell the winner
    assert "بیت‌کوین" in first["note_fa"]
    held = {a: D(q) for a, q in r["final_holdings"].items()}
    assert all(q >= 0 for q in held.values())
    assert D(r["fees_tmn"]) > 0
    # Rebalancing a one-way rally gives up some upside vs holding: reported, not hidden.
    assert r["rebalanced"]["return_pct"] < r["hold"]["return_pct"]


def test_portfolio_api(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as c:
        r = c.post("/api/m/portfolio/backtest", json={}).json()
        assert "rebalanced" in r and "hold" in r and r["curve"]
        s = c.post(
            "/api/m/portfolio/suggest",
            json={"targets": {"TMN": 50, "BTC": 50}, "holdings": {"TMN": 100_000_000, "BTC": 0}},
        ).json()
        assert s["orders"] and s["orders"][0]["side"] == "buy" and "پیشنهاد" in s["note_fa"]
        bad = c.post("/api/m/portfolio/backtest", json={"targets": {"DOGE": 100}})
        assert bad.status_code == 422


# ---- alerts -------------------------------------------------------------------------------------
def test_alert_conditions_and_external_channels(tmp_path: Path) -> None:
    from zirak.modules import alerts

    assert alerts.condition_met("price_above", 10, 11) and not alerts.condition_met("price_above", 10, 9)
    assert alerts.condition_met("rsi_below", 30, 25) and not alerts.condition_met("rsi_below", 30, None)
    sent: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        sent.append(str(r.url))
        return httpx.Response(200, json={"ok": True})

    s = settings(
        tmp_path,
        alerts_telegram_token="T",
        alerts_telegram_chat_id="1",
        alerts_bale_token="B",
        alerts_bale_chat_id="2",
    )
    channels = asyncio.run(alerts.notify(s, "hi", httpx.MockTransport(handler)))
    assert channels == ["in_app", "telegram", "bale"]
    assert sent == ["https://api.telegram.org/botT/sendMessage", "https://tapi.bale.ai/botB/sendMessage"]
    assert asyncio.run(alerts.notify(settings(tmp_path), "hi")) == ["in_app"]  # nothing configured: no I/O


def test_alerts_api_fire_once_and_persist(tmp_path: Path) -> None:
    s = settings(tmp_path, alerts_interval_s=0)
    with TestClient(create_app(s)) as c:
        a = c.post("/api/m/alerts", json={"symbol": "BTCTMN", "kind": "price_above", "value": 1}).json()
        c.post("/api/m/alerts", json={"symbol": "BTCTMN", "kind": "price_below", "value": 1})
        fired = c.post("/api/m/alerts/check").json()["fired"]
        assert [f["alert_id"] for f in fired] == [a["id"]] and "توصیهٔ مالی نیست" in fired[0]["message_fa"]
        assert c.post("/api/m/alerts/check").json()["fired"] == []  # `once`: deactivated
        listing = c.get("/api/m/alerts").json()
        assert len(listing["alerts"]) == 2 and listing["events"] and not listing["channels"]["telegram"]
    with TestClient(create_app(s)) as c:  # persisted across restarts
        assert len(c.get("/api/m/alerts").json()["alerts"]) == 2
        assert c.delete(f"/api/m/alerts/{a['id']}").json()["deleted"]


# ---- coach --------------------------------------------------------------------------------------
def test_coach_finds_fomo_panic_and_big_losses() -> None:
    from zirak.modules import coach

    # Price: rally 100 -> 110 over a day, crash to 90, recover to 100.
    closes = [100 + i * 10 / 24 for i in range(25)] + [110 - i * 20 / 24 for i in range(1, 25)]
    closes += [90 + i * 10 / 24 for i in range(1, 25)]
    candles = series(closes)

    def at(h: int) -> datetime:
        return T0 + timedelta(hours=h)

    trades = [
        coach.TradeIn(at(24), "buy", 110, 1, 0.3),  # bought the top after +10 % in a day
        coach.TradeIn(at(48), "sell", 90, 1, 0.2),  # sold the bottom after -18 %, recovered next day
    ]
    findings = {f.code: f for f in coach.review(trades, candles)}
    assert {"chasing_pumps", "panic_selling", "no_stop_loss"} <= set(findings)
    assert findings["chasing_pumps"].examples == [0] and findings["panic_selling"].examples == [1]
    out = asyncio.run(coach.coach(trades, candles, MockLLM()))
    assert out["score"] < 60 and "توصیهٔ مالی نیست" in out["summary_fa"]
    calm = [coach.TradeIn(at(10), "buy", 104.17, 1), coach.TradeIn(at(20), "sell", 108.33, 1)]
    assert [f.code for f in coach.review(calm, candles)] == ["disciplined"]


def test_coach_round_trips_average_cost() -> None:
    from zirak.modules import coach

    t = [
        coach.TradeIn(T0, "buy", 100, 1),
        coach.TradeIn(T0 + timedelta(hours=1), "buy", 80, 1),
        coach.TradeIn(T0 + timedelta(hours=2), "sell", 99, 2),
    ]
    (rt,) = coach.round_trips(t)
    assert rt.pnl == 18 and round(rt.pnl_pct, 3) == 10.0


def test_coach_api_on_the_emotional_trader(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as c:
        r = c.post("/api/m/coach", json={"source": "emotional"}).json()
        assert r["trades"] > 0 and r["findings"] and 0 <= r["score"] <= 100
        assert c.post("/api/m/coach", json={"source": "bot"}).status_code == 404
        assert c.post("/api/m/coach", json={"source": "backtest", "report_id": "../x"}).status_code == 404


# ---- competition --------------------------------------------------------------------------------
def test_competition_runs_writes_files_and_team_stop_kills(tmp_path: Path) -> None:
    from zirak.data.source import build_replay
    from zirak.modules.competition import Competition, CompetitionIn

    s = settings(tmp_path)
    replay, _ = build_replay(s)
    cfg = CompetitionIn.model_validate(
        {
            "name": "t1",
            "entries": [
                {
                    "name": "a",
                    "strategy": "dca",
                    "params": {"every": 1, "size_pct": 20},
                    "symbol": "BTCTMN",
                    "capital_pct": 40,
                },
                {"name": "b", "strategy": "rsi_reversion", "symbol": "ETHUSDT", "capital_pct": 50},
            ],
            "speed_s": 0.0,
            "write_every_s": 0.05,
            "max_drawdown_pct": 50,
            "daily_loss_pct": 50,
        }
    )
    comp = Competition(s, cfg, replay)

    async def scenario() -> dict[str, Any]:
        await comp.start()
        for _ in range(200):
            await asyncio.sleep(0.05)
            if not comp.running:
                break
        await comp.stop()
        return await comp.performance()

    perf = asyncio.run(scenario())
    out = tmp_path / "competition" / "t1"
    saved = __import__("json").loads((out / "performance.json").read_text(encoding="utf-8"))
    assert {e["name"] for e in saved["entries"]} == {"a", "b"}
    assert D(saved["start_equity_tmn"]) > 0 and saved["usdt_tmn"]
    a = next(e for e in perf["entries"] if e["name"] == "a")
    assert D(a["start_equity"]) == s.paper_start_tmn * D("0.4")  # its sleeve, not the whole account
    assert (out / "trades.jsonl").read_text(encoding="utf-8").strip()
    assert (out / "equity.csv").read_text(encoding="utf-8").startswith("ts,total_equity_tmn")


def test_competition_team_drawdown_engages_kill_switch(tmp_path: Path) -> None:
    from zirak.data.source import build_replay
    from zirak.modules.competition import Competition, CompetitionIn

    s = settings(tmp_path)
    replay, _ = build_replay(s)
    cfg = CompetitionIn.model_validate(
        {
            "name": "t2",
            "entries": [
                {
                    "name": "a",
                    "strategy": "dca",
                    "params": {"every": 1, "size_pct": 50},
                    "symbol": "BTCTMN",
                    "capital_pct": 100,
                }
            ],
            "speed_s": 0.005,
            "write_every_s": 0.05,
            "max_drawdown_pct": 0.01,
            "daily_loss_pct": 50,
            "risk": {"stop_loss_pct": None, "daily_loss_limit_pct": None},
        }
    )
    comp = Competition(s, cfg, replay)

    async def scenario() -> None:
        await comp.start()
        for _ in range(200):
            await asyncio.sleep(0.05)
            if not comp.running:
                break
        await comp.stop()

    asyncio.run(scenario())
    assert comp.stopped_reason and "drawdown" in comp.stopped_reason
    assert s.kill_file.exists()
    assert all(r.bot is not None and r.bot.risk.killed for r in comp.runners.values())


def test_competition_api_and_capital_check(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as c:
        cfg = c.get("/api/m/competition/default-config").json()
        bad = {
            **cfg,
            "entries": [
                {**cfg["entries"][0], "capital_pct": 80},
                {**cfg["entries"][1], "capital_pct": 0.5},
                {**cfg["entries"][2], "capital_pct": 30},
            ],
        }
        assert c.post("/api/m/competition/start", json=bad).status_code == 422  # 110 % of TMN
        r = c.post("/api/m/competition/start", json={**cfg, "speed_s": 0.05}).json()
        assert len(r["entries"]) == 3
        k = c.post("/api/m/competition/kill").json()
        assert k["kill_engaged"] and not k["running"]
