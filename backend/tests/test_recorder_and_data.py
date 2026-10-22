import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import httpx

from tests.conftest import candle
from tests.test_wallex_client import MARKETS, Fake, ok, udf_server
from zirak.config import WALLEX_SAMPLE_DIR, Settings
from zirak.data.aggregate import aggregate
from zirak.data.recorder import Recorder, backfill, save_markets
from zirak.data.source import build_replay, is_synthetic
from zirak.data.store import Store
from zirak.engine.executor import Executor
from zirak.exchange.wallex import WallexClient
from zirak.exchange.wallex_ws import _Books, parse_channel_message
from zirak.markets import DEFAULT_MARKETS
from zirak.models import OrderRequest, OrderType, Side, utcnow


def fake_wallex() -> Fake:
    start = utcnow().replace(second=0, microsecond=0) - timedelta(days=3)
    return Fake(
        {
            "GET /hector/web/v1/markets": ok(MARKETS),
            "GET /v1/udf/history": udf_server(start, 3 * 24 * 60, 60, cap=1440),
            "GET /v1/depth": ok(
                {
                    "ask": [{"price": 101, "quantity": 2, "sum": "202"}],
                    "bid": [{"price": 99, "quantity": 1, "sum": "99"}],
                }
            ),
            "GET /v1/trades": ok(
                {
                    "latestTrades": [
                        {
                            "symbol": "BTCTMN",
                            "quantity": "1",
                            "price": "100",
                            "sum": "100",
                            "isBuyOrder": True,
                            "timestamp": "2026-10-22T08:00:00Z",
                        }
                    ]
                }
            ),
        }
    )


def test_recorder_tasks_write_to_store(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL")
    c = WallexClient(settings, transport=httpx.MockTransport(fake_wallex()))
    store = Store(tmp_path / "db.sqlite")
    rec = Recorder(c, store, ["BTCTMN"], ["1m"], 0.01, 0.01, 0.01, tmp_path / "status.json")
    asyncio.run(rec.run(duration_s=0.3))
    status = json.loads((tmp_path / "status.json").read_text())
    assert all(t["errors"] == 0 and t["runs"] >= 1 for t in status["tasks"].values())
    assert store.last_candle_ts("BTCTMN", "1m") is not None
    assert len(store.load_books("BTCTMN")) >= 1
    assert len(store.load_trades("BTCTMN")) == 1  # repeated polls don't duplicate trades


def test_backfill_and_market_snapshot(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL")
    c = WallexClient(settings, transport=httpx.MockTransport(fake_wallex()))
    store = Store(tmp_path / "db.sqlite")
    counts = asyncio.run(backfill(c, store, ["BTCTMN"], {"1m": 1}, progress=lambda _m: None))
    assert counts["BTCTMN_1m"] >= 1400
    assert asyncio.run(save_markets(c, tmp_path / "markets.json")) == 2


def test_aggregate_buckets_and_skips_unfinished() -> None:
    ones = [candle(i, "1", str(2 + i), "0.5", str(1 + i), "1") for i in range(9)]  # 9 hourly candles
    four = aggregate(ones, "4h")
    assert [c.ts.hour for c in four] == [0, 4, 8]
    assert four[0].high == D("5") and four[0].close == D("4") and four[0].volume == D("4")
    finished = aggregate(ones, "4h", until=ones[-1].ts + timedelta(hours=1))
    assert len(finished) == 2  # the 08:00 bucket has only one hour so far


def test_real_sample_loads_with_real_precision() -> None:
    assert not is_synthetic(WALLEX_SAMPLE_DIR)
    replay, label = build_replay(Settings(replay_dir=WALLEX_SAMPLE_DIR, db_path=Path("missing.sqlite")))
    assert label == "recorded"
    assert replay.markets["BTCTMN"].qty_step == D("0.00000001") and replay.markets["BTCTMN"].verified
    assert len(replay.series("BTCTMN", "1h")) > 1000
    assert replay.series("BTCTMN", "4h") and replay.series("BTCTMN", "15m")  # derived on load


def test_ws_parsing_v1_and_v2_bodies() -> None:
    books = _Books()
    t = parse_channel_message(
        "public:BTCTMN@trade",
        {
            "isBuyOrder": True,
            "quantity": "0.000243",
            "price": "15791249224",
            "timestamp": "2026-08-25T16:38:23Z",
        },
        books,
    )
    assert (
        t is not None
        and t.trade is not None
        and t.trade.side is Side.SELL
        and t.trade.price == D("15791249224")
    )
    parse_channel_message("BTCTMN@buyDepth", [{"quantity": 255.75, "price": 82131, "sum": 1}], books)
    e = parse_channel_message(
        "orderbook:BTCTMN@sellDepth", [{"quantity": 1, "price": 82200, "sum": 1}], books
    )
    assert e is not None and e.book is not None
    assert e.book.best_bid == D("82131") and e.book.best_ask == D("82200")
    assert parse_channel_message("public:all@price", {"symbol": "X"}, books) is None


def test_live_market_orders_become_protected_limits(tmp_path: Path) -> None:
    m = DEFAULT_MARKETS["USDTTMN"]
    ex = Executor(WallexClient(Settings(kill_file=tmp_path / "K")), m)
    buy = ex.protect(OrderRequest("USDTTMN", Side.BUY, OrderType.MARKET, D("10")), D("268000"), D("50"))
    assert buy.type is OrderType.LIMIT and buy.price == D("269340")  # +0.5 %, rounded up to the tick
    sell = ex.protect(OrderRequest("USDTTMN", Side.SELL, OrderType.MARKET, D("10")), D("268000"), D("50"))
    assert sell.price == D("266660")
    keep = OrderRequest("USDTTMN", Side.BUY, OrderType.LIMIT, D("10"), D("1"))
    assert ex.protect(keep, D("268000"), D("50")) is keep


def test_live_order_shrinks_to_fit_the_hard_cap_after_protection(tmp_path: Path) -> None:
    """Sized to exactly MAX_ORDER_TMN at the close, a protected (+0.5 %) price must not trip the hard cap."""
    m = DEFAULT_MARKETS["USDTTMN"]
    ex = Executor(WallexClient(Settings(kill_file=tmp_path / "K")), m)
    cap = D("1000000")
    req = ex.protect(OrderRequest("USDTTMN", Side.BUY, OrderType.MARKET, D("3.73")), D("268000"), D("50"))
    assert req.price is not None and req.qty * req.price > cap  # 3.73 * 269340 = 1,004,638 > cap
    fitted = ex.fit_cap(req, cap)
    assert fitted is not None and fitted.price is not None
    assert fitted.qty == D("3.71") and fitted.qty * fitted.price <= cap
    assert ex.fit_cap(req, None) is req
    assert ex.fit_cap(req, D("50000")) is None  # below the market minimum after shrinking


def test_bot_cancels_stale_live_orders(tmp_path: Path) -> None:
    """Order TTL: an unfilled order older than order_ttl_s is canceled at the next sync."""
    from tests.conftest import make_paper
    from zirak.engine.bot import Bot, SimClock
    from zirak.engine.risk import RiskConfig, RiskManager
    from zirak.fees import FeeModel
    from zirak.models import Market
    from zirak.strategy.registry import build_strategy

    market = Market("TESTUSDT", "TST", "USDT", D("0.01"), D("0.001"), D("0.001"), D("5"))
    paper, _ = make_paper(market, FeeModel(D("0.001"), D("0.002")))
    clock = SimClock(datetime(2026, 1, 1, tzinfo=UTC))
    paper.clock = clock
    bot = Bot(
        build_strategy("dca"),
        RiskManager(RiskConfig(), market),
        paper,
        market,
        "1h",
        clock=clock,
        fill_on_candle=False,
        order_ttl_s=30,
    )
    order = asyncio.run(
        paper.place_order(OrderRequest("TESTUSDT", Side.BUY, OrderType.LIMIT, D("1"), D("90")))
    )
    bot._open[order.id] = None  # type: ignore[assignment]
    bot._track = lambda order, entry: None  # type: ignore[method-assign]
    clock.now += timedelta(seconds=10)
    asyncio.run(bot.sync_orders())
    assert order.status.is_open
    clock.now += timedelta(seconds=30)
    asyncio.run(bot.sync_orders())
    assert not order.status.is_open
