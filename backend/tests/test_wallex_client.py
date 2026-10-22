"""WallexClient against a mocked HTTP transport (shapes from docs/wallex-api + live probes)."""

import asyncio
import itertools
import json
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
import pytest

from zirak.config import Settings
from zirak.exchange.guard import LiveTradingDisabled
from zirak.exchange.wallex import WallexAPIError, WallexClient, flatten_orders
from zirak.models import OrderRequest, OrderStatus, OrderType, Side, utcnow


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class Fake:
    """Routes requests to handlers and records every call."""

    def __init__(self, routes: dict[str, Callable[[httpx.Request], httpx.Response]]) -> None:
        self.routes = routes
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = f"{request.method} {request.url.path}"
        for route, handler in self.routes.items():
            if key == route or (route.endswith("*") and key.startswith(route[:-1])):
                return handler(request)
        return httpx.Response(404, json={"success": False, "message": "not mocked"})


def client(settings: Settings, fake: Fake) -> WallexClient:
    return WallexClient(settings, transport=httpx.MockTransport(fake))


def ok(result: Any) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _r: httpx.Response(200, json={"result": result, "message": "ok", "success": True})


MARKETS = {
    "markets": [
        {
            "symbol": "BTCTMN",
            "base_asset": "BTC",
            "quote_asset": "TMN",
            "amount_precision": 8,
            "price_precision": 0,
            "is_spot": True,
        },
        {
            "symbol": "ETHUSDT",
            "base_asset": "ETH",
            "quote_asset": "USDT",
            "amount_precision": 5,
            "price_precision": 2,
            "is_spot": True,
        },
        {
            "symbol": "OTCONLY",
            "base_asset": "X",
            "quote_asset": "TMN",
            "amount_precision": 0,
            "price_precision": 0,
            "is_spot": False,
        },
    ]
}


def test_markets_precision_to_steps(settings: Settings) -> None:
    c = client(settings, Fake({"GET /hector/web/v1/markets": ok(MARKETS)}))
    ms = {m.symbol: m for m in run(c.get_markets())}
    assert set(ms) == {"BTCTMN", "ETHUSDT"}  # non-spot markets are skipped
    assert ms["BTCTMN"].price_step == D("1") and ms["BTCTMN"].qty_step == D("0.00000001")
    assert ms["ETHUSDT"].price_step == D("0.01") and ms["ETHUSDT"].qty_step == D("0.00001")
    assert ms["BTCTMN"].verified


def test_public_calls_send_key_only_when_set(settings: Settings) -> None:
    fake = Fake({"GET /hector/web/v1/markets": ok(MARKETS)})
    run(client(settings, fake).get_markets())
    assert "x-api-key" not in fake.calls[0].headers
    fake2 = Fake({"GET /hector/web/v1/markets": ok(MARKETS)})
    run(client(replace(settings, wallex_api_key="k123"), fake2).get_markets())
    assert fake2.calls[0].headers["x-api-key"] == "k123"


def test_depth_numbers_become_exact_decimals(settings: Settings) -> None:
    depth = {
        "ask": [
            {"price": 22140000000, "quantity": 0.000148, "sum": "3276720"},
            {"price": 22138741800, "quantity": 0.00164563, "sum": "1"},
        ],
        "bid": [
            {"price": 22131272732, "quantity": 0.1, "sum": "1"},
            {"price": 22131272733, "quantity": 0.00349668, "sum": "1"},
        ],
    }
    fake = Fake({"GET /v1/depth": ok(depth)})
    book = run(client(settings, fake).get_order_book("BTCTMN"))
    assert fake.calls[0].url.params["symbol"] == "BTCTMN"
    assert book.best_ask == D("22138741800") and book.best_bid == D("22131272733")
    assert book.asks[0].qty == D("0.00164563")  # float went through str(), so it stays exact


def test_trades_side_is_the_aggressor(settings: Settings) -> None:
    trades = {
        "latestTrades": [
            {
                "symbol": "BTCTMN",
                "quantity": "0.0035140200000000",
                "price": "22132140161.0000000000000000",
                "sum": "1",
                "isBuyOrder": False,
                "timestamp": "2026-10-22T08:14:49Z",
            },
            {
                "symbol": "BTCTMN",
                "quantity": "0.00000399",
                "price": "22131272732",
                "sum": "1",
                "isBuyOrder": True,
                "timestamp": "2026-10-22T08:13:56Z",
            },
        ]
    }
    out = run(client(settings, Fake({"GET /v1/trades": ok(trades)})).get_recent_trades("BTCTMN"))
    assert [t.side for t in out] == [Side.SELL, Side.BUY]  # oldest first; maker buy -> taker sold
    assert out[1].price == D("22132140161") and str(out[1].qty) == "0.00351402"


def udf_server(start: datetime, n: int, step: int, cap: int) -> Callable[[httpx.Request], httpx.Response]:
    """Serves n candles from `start`; like Wallex, returns only the most recent `cap` bars of a window."""
    ts = [int(start.timestamp()) + i * step for i in range(n)]

    def handler(r: httpx.Request) -> httpx.Response:
        lo, hi = int(r.url.params["from"]), int(r.url.params["to"])
        sel = [t for t in ts if lo <= t <= hi][-cap:]
        if not sel:
            return httpx.Response(200, json={"s": "no_data"})
        px = [str(100 + (t - ts[0]) // step) for t in sel]
        return httpx.Response(
            200, json={"s": "ok", "t": sel, "o": px, "h": px, "l": px, "c": px, "v": ["1.5"] * len(sel)}
        )

    return handler


def test_candles_page_backwards_through_the_cap(settings: Settings) -> None:
    end = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
    start = end - timedelta(hours=2000)
    fake = Fake({"GET /v1/udf/history": udf_server(start, 2000, 3600, cap=700)})
    c = client(settings, fake)
    out = run(c.get_candles("BTCTMN", "1h", start, end))
    assert len(out) == 2000
    assert all((b.ts - a.ts) == timedelta(hours=1) for a, b in itertools.pairwise(out))
    assert all(r.url.params["resolution"] == "60" for r in fake.calls)


def test_candles_exclude_the_open_candle_and_aggregate_15m(settings: Settings) -> None:
    now = utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(minutes=120)
    fake = Fake({"GET /v1/udf/history": udf_server(start, 121, 60, cap=5000)})  # includes the open minute
    c = client(settings, fake)
    one = run(c.get_candles("BTCTMN", "1m", start, utcnow()))
    assert one and one[-1].ts + timedelta(minutes=1) <= utcnow()
    fifteen = run(c.get_candles("BTCTMN", "15m", start, utcnow()))
    assert fifteen and all(x.ts.minute % 15 == 0 for x in fifteen)
    assert all(fake_call.url.params["resolution"] == "1" for fake_call in fake.calls)


def test_get_retries_on_429_then_succeeds(settings: Settings) -> None:
    state = {"n": 0}

    def flaky(_r: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(
                429, headers={"retry-after": "0"}, json={"success": False, "message": "slow"}
            )
        return httpx.Response(200, json={"result": MARKETS, "success": True})

    assert len(run(client(settings, Fake({"GET /hector/web/v1/markets": flaky})).get_markets())) == 2
    assert state["n"] == 2


def test_api_error_surfaces(settings: Settings) -> None:
    fake = Fake(
        {
            "GET /v1/depth": lambda _r: httpx.Response(
                400, json={"success": False, "message": "bad", "code": 400}
            )
        }
    )
    with pytest.raises(WallexAPIError):
        run(client(settings, fake).get_order_book("X"))


# ---- private endpoints ---------------------------------------------------------------------------
def live(tmp: Path) -> Settings:
    return Settings(
        live_trading=True,
        max_order_tmn=D("1000000"),
        max_order_usdt=D("20"),
        daily_loss_limit_pct=D("2"),
        wallex_api_key="test-key",
        kill_file=tmp / "KILL",
    )


ORDER = {
    "clientOrderId": "zirak_abc",
    "symbol": "USDTTMN",
    "type": "LIMIT",
    "side": "BUY",
    "price": "268000",
    "origQty": "10",
    "executedQty": "4",
    "executedSum": "1072000",
    "executedPrice": "268000",
    "fee": "0.01",
    "status": "NEW",
    "active": True,
    "created_at": "2026-10-22T08:00:00Z",
    "fills": [{"price": "268000", "quantity": "4", "sum": "1072000", "fee": "0.01", "feeAsset": "USDT"}],
}


def test_no_request_is_made_when_live_is_off(settings: Settings) -> None:
    fake = Fake({"POST /v1/account/orders": ok(ORDER)})
    c = client(settings, fake)
    with pytest.raises(LiveTradingDisabled):
        run(c.place_order(OrderRequest("USDTTMN", Side.BUY, OrderType.LIMIT, D("10"), D("268000"))))
    assert fake.calls == []


def test_place_order_body_and_parse(tmp_path: Path) -> None:
    fake = Fake(
        {"POST /v1/account/orders": lambda _r: httpx.Response(201, json={"result": ORDER, "success": True})}
    )
    c = client(live(tmp_path), fake)
    order = run(c.place_order(OrderRequest("USDTTMN", Side.BUY, OrderType.LIMIT, D("10"), D("268000"))))
    body = json.loads(fake.calls[0].content)
    assert body["side"] == "BUY" and body["type"] == "LIMIT"
    assert body["price"] == "268000" and body["quantity"] == "10"  # strings, as documented
    assert body["client_id"].startswith("zirak_") and set(body["client_id"]) <= set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    )
    assert fake.calls[0].headers["x-api-key"] == "test-key"
    assert order.status is OrderStatus.PARTIALLY_FILLED and order.filled_qty == D("4")
    assert order.fee_asset == "USDT" and order.avg_price == D("268000")


def test_market_orders_are_refused_by_the_client(tmp_path: Path) -> None:
    c = client(live(tmp_path), Fake({}))
    with pytest.raises(ValueError):
        run(c.place_order(OrderRequest("USDTTMN", Side.BUY, OrderType.MARKET, D("10"))))


def test_cancel_and_open_orders(tmp_path: Path) -> None:
    canceled = {**ORDER, "status": "CANCELED", "active": False}
    fake = Fake(
        {
            "DELETE /v1/account/orders/*": ok(canceled),
            "GET /v1/account/openOrders": ok(
                {"USDTTMN": [ORDER], "BTCTMN": [{**ORDER, "clientOrderId": "z2"}]}
            ),
        }
    )
    c = client(live(tmp_path), fake)
    assert run(c.cancel_order("USDTTMN", "zirak_abc")).status is OrderStatus.CANCELED
    assert fake.calls[0].url.path == "/v1/account/orders/zirak_abc"
    assert {o.id for o in run(c.get_open_orders())} == {"zirak_abc", "z2"}


def test_flatten_orders_shapes() -> None:
    assert flatten_orders([ORDER]) == [ORDER]
    assert flatten_orders({"orders": [ORDER]}) == [ORDER]
    assert flatten_orders({"a": [ORDER], "b": []}) == [ORDER]
    assert flatten_orders(ORDER) == [ORDER]
    assert flatten_orders(None) == []


def test_unknown_status_inferred_from_active_flag(tmp_path: Path) -> None:
    c = client(live(tmp_path), Fake({}))
    done = c._parse_order({**ORDER, "status": "WEIRD", "active": False, "executedQty": "10"})
    assert done.status is OrderStatus.FILLED
    gone = c._parse_order({**ORDER, "status": None, "active": False, "executedQty": "0"})
    assert gone.status is OrderStatus.CANCELED


def test_balances_free_is_value_minus_locked(tmp_path: Path) -> None:
    bal = {"balances": {"TMN": {"asset": "TMN", "value": "16033085", "locked": "2507491"}}}
    out = run(client(live(tmp_path), Fake({"GET /v1/account/balances": ok(bal)})).get_balances())
    assert out["TMN"].free == D("13525594") and out["TMN"].total == D("16033085")
