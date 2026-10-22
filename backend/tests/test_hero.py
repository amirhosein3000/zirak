"""Hero features: periods/time machine, Zirak Score, risk shield, duel, mood, live pre-flight and the
guarded real-money runner (against a mocked Wallex)."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from tests.conftest import candle
from tests.test_wallex_client import MARKETS, Fake, ok, udf_server
from zirak.api.main import LIVE_CONFIRM_PHRASE, create_app
from zirak.backtest.insights import select_period, worst_drawdown, zirak_score
from zirak.config import SAMPLE_DATA_DIR, Settings
from zirak.engine.risk import RiskConfig
from zirak.engine.runner import BotRunner, RunnerError
from zirak.exchange.replay import ReplayExchange
from zirak.exchange.wallex import WallexClient
from zirak.llm.brief import mood_label, mood_score
from zirak.models import utcnow
from zirak.strategy.registry import build_strategy


def test_worst_drawdown_and_crash_period() -> None:
    prices = [100, 110, 120, 90, 80, 100, 115, 105]
    series = [candle(i, str(p), str(p), str(p), str(p)) for i, p in enumerate(prices * 30)]
    p, t, dd = worst_drawdown(series[:8])
    assert (p, t) == (2, 4) and round(dd, 2) == -33.33
    crash = select_period(series, "crash", "1h")
    assert crash.key == "crash" and crash.note_fa and len(crash.candles) > 0
    last30 = select_period(series, "30d", "1h")
    assert len(last30.candles) == len(series)  # shorter than 30 days: everything


def test_score_is_bounded_and_graded() -> None:
    great = {
        "return_pct": 25,
        "max_drawdown_pct": -3,
        "buy_hold_return_pct": 5,
        "buy_hold_max_drawdown_pct": -20,
        "trades": 20,
        "win_rate_pct": 70,
    }
    awful = {
        "return_pct": -30,
        "max_drawdown_pct": -45,
        "buy_hold_return_pct": 10,
        "buy_hold_max_drawdown_pct": -10,
        "trades": 20,
        "win_rate_pct": 10,
    }
    g, a = zirak_score(great), zirak_score(awful)
    assert 0 <= a["score"] < g["score"] <= 100
    assert g["grade"] == "A" and a["grade"] == "E" and g["headline_fa"] and a["details_fa"]


def test_mood_gauge() -> None:
    assert mood_score("up", 75, 5, 40) >= 80 and mood_label(mood_score("up", 75, 5, 40)) == "هیجان و طمع"
    assert mood_score("down", 25, -6, -40) <= 20
    assert 40 <= mood_score("range", 50, 0, 0) <= 60


def client(tmp_path: Path, **kw: Any) -> TestClient:
    s = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "none.sqlite",
        kill_file=tmp_path / "KILL",
        replay_dir=SAMPLE_DATA_DIR,
    )
    return TestClient(create_app(replace(s, **kw)))


def test_backtest_has_score_shield_and_period(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        r = c.post(
            "/api/backtest", json={"strategy": "rsi_reversion", "symbol": "BTCTMN", "period": "crash"}
        ).json()
        assert r["period"]["key"] == "crash" and r["period"]["note_fa"]
        assert 0 <= r["score"]["score"] <= 100
        sh = r["shield"]
        assert {"saved_quote", "drawdown_cut_pct", "message_fa", "without_curve"} <= set(sh)
        assert len(sh["without_curve"]) > 10


def test_duel_ranks_everyone_including_the_emotional_trader(tmp_path: Path) -> None:
    spec = {
        "symbol": "BTCTMN",
        "entry": [{"kind": "drop_from_high", "pct": 4, "lookback": 24}],
        "position_size_pct": 20,
        "take_profit_pct": 3,
        "stop_loss_pct": 4,
    }
    with client(tmp_path) as c:
        d = c.post("/api/duel", json={"strategy": "rules", "spec": spec, "period": "90d"}).json()
    keys = [r["key"] for r in d["rows"]]
    assert {"yours", "fomo", "buy_hold", "ema_cross"} <= set(keys)
    assert [r["rank"] for r in d["rows"]] == list(range(1, len(keys) + 1))
    assert d["rows"] == sorted(d["rows"], key=lambda r: -r["score"])
    assert "رتبهٔ" in d["headline_fa"]


def test_preflight_without_key_is_not_ready_and_live_start_is_refused(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        pf = c.get("/api/live/preflight").json()
        assert pf["ready"] is False
        assert {ch["key"] for ch in pf["checks"]} >= {
            "live_flag",
            "order_caps",
            "daily_loss",
            "kill_switch",
            "api_key",
        }
        assert c.post("/api/live/start", json={"strategy": "dca"}).status_code == 400  # no confirmation
        r = c.post("/api/live/start", json={"strategy": "dca", "confirm": LIVE_CONFIRM_PHRASE})
        assert r.status_code == 409  # confirmed, but the pre-flight fails


def test_runner_refuses_real_mode_when_not_live(tmp_path: Path) -> None:
    s = Settings(kill_file=tmp_path / "KILL", data_source="wallex")
    runner = BotRunner(s, ReplayExchange({}), WallexClient(s))
    try:
        asyncio.run(runner.start(build_strategy("dca"), RiskConfig(), "BTCTMN", "1m", real=True))
        raise AssertionError("should have refused")
    except RunnerError as e:
        assert "LIVE_TRADING" in str(e)


def test_real_mode_sends_capped_limit_orders_and_kill_cancels(tmp_path: Path) -> None:
    """End to end against a mocked Wallex: real mode, DCA buys, every order is a capped LIMIT,
    and the kill switch cancels what is open."""
    s = Settings(
        live_trading=True,
        max_order_tmn=D("1000000"),
        max_order_usdt=D("20"),
        daily_loss_limit_pct=D("2"),
        wallex_api_key="k",
        kill_file=tmp_path / "KILL",
        data_source="wallex",
        live_poll_s=0.01,
        live_order_ttl_s=3600,
    )
    start = utcnow().replace(second=0, microsecond=0) - timedelta(hours=3)
    placed: list[dict[str, Any]] = []
    open_orders: dict[str, dict[str, Any]] = {}

    def place(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        placed.append(body)
        o = {
            "clientOrderId": body["client_id"],
            "symbol": body["symbol"],
            "side": body["side"],
            "type": "LIMIT",
            "price": body["price"],
            "origQty": body["quantity"],
            "executedQty": "0",
            "status": "NEW",
            "active": True,
            "created_at": utcnow().isoformat(),
        }
        open_orders[o["clientOrderId"]] = o
        return httpx.Response(201, json={"result": o, "success": True})

    def get_or_cancel(r: httpx.Request) -> httpx.Response:
        oid = r.url.path.rsplit("/", 1)[-1]
        o = open_orders[oid]
        if r.method == "DELETE":
            o = {**o, "status": "CANCELED", "active": False}
            open_orders[oid] = o
        return httpx.Response(200, json={"result": o, "success": True})

    fake = Fake(
        {
            "GET /hector/web/v1/markets": ok(
                {
                    "markets": [
                        *MARKETS["markets"],
                        {
                            "symbol": "USDTTMN",
                            "base_asset": "USDT",
                            "quote_asset": "TMN",
                            "amount_precision": 2,
                            "price_precision": 0,
                            "is_spot": True,
                        },
                    ]
                }
            ),
            "GET /v1/udf/history": udf_server(start, 180, 60, cap=1440),
            "GET /v1/depth": ok(
                {
                    "ask": [{"price": 270000, "quantity": 100, "sum": "1"}],
                    "bid": [{"price": 269000, "quantity": 100, "sum": "1"}],
                }
            ),
            "GET /v1/account/balances": ok(
                {
                    "balances": {
                        "TMN": {"asset": "TMN", "value": "2000000", "locked": "0"},
                        "USDT": {"asset": "USDT", "value": "0", "locked": "0"},
                    }
                }
            ),
            "POST /v1/account/orders": place,
            "GET /v1/account/orders/*": get_or_cancel,
            "DELETE /v1/account/orders/*": get_or_cancel,
            "GET /v1/account/openOrders": lambda _r: httpx.Response(
                200, json={"result": [o for o in open_orders.values() if o["active"]], "success": True}
            ),
        }
    )
    live = WallexClient(s, transport=httpx.MockTransport(fake))
    runner = BotRunner(s, ReplayExchange({}), live)

    async def scenario() -> None:
        # Feed one extra closed candle so the strategy acts on "new" data.
        await runner.start(
            build_strategy("dca", {"every": 1, "size_pct": 40}), RiskConfig(), "USDTTMN", "1m", real=True
        )
        assert runner.mode == "live"
        assert runner.bot is not None
        await runner.bot.on_candle(candle(10_000, "268000", "268000", "268000", "268000", "100"))
        await runner.kill("test")

    asyncio.run(scenario())
    assert placed, "no order reached the (mocked) exchange"
    for body in placed:
        assert body["type"] == "LIMIT"
        assert D(body["price"]) * D(body["quantity"]) <= D("1000000")  # hard cap from the environment
    assert all(not o["active"] for o in open_orders.values()), "kill switch left an order open"
