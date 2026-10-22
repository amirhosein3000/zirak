"""Optional modules (zirak/modules): pure logic plus their API routes, fully offline."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

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
