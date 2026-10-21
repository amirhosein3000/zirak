import asyncio
from collections.abc import Coroutine
from decimal import Decimal as D
from typing import Any

from tests.conftest import T0, candle, make_paper
from zirak.fees import FeeModel
from zirak.models import Market, OrderRequest, OrderStatus, OrderType, Side


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_market_buy_fills_next_candle_open_with_fee(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees)
    order = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.MARKET, D("2"))))
    assert order.status is OrderStatus.NEW  # not filled until the next candle
    paper.on_candle(market.symbol, candle(1, "101", "102", "100", "101"))
    assert order.status is OrderStatus.FILLED
    assert order.avg_price == D("101")
    bal = run(paper.get_balances())
    assert bal["TST"].free == D("1.996")  # 2 - 0.2 % taker fee in base
    assert bal["USDT"].total == D("1000") - D("202")
    assert bal["USDT"].locked == 0


def test_market_sell_with_slippage(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees, quote="0", base="1", slippage_bps="10")
    order = run(paper.place_order(OrderRequest(market.symbol, Side.SELL, OrderType.MARKET, D("1"))))
    paper.on_candle(market.symbol, candle(1, "100", "100", "100", "100"))
    assert order.avg_price == D("99.90")
    bal = run(paper.get_balances())
    assert bal["USDT"].free == D("99.90") * (1 - D("0.002"))
    assert bal["TST"].total == 0


def test_partial_fill_by_volume_participation(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees, participation="0.1")
    # Candle volume 10 -> at most 1 unit can fill; market orders are IOC so the rest is canceled.
    order = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.MARKET, D("3"))))
    paper.on_candle(market.symbol, candle(1, "100", "100", "100", "100", v="10"))
    assert order.filled_qty == D("1")
    assert order.status is OrderStatus.FILLED
    assert order.reject_reason == "partial_fill_remainder_canceled"
    bal = run(paper.get_balances())
    assert bal["USDT"].locked == 0  # reserve released
    assert bal["USDT"].free == D("900")


def test_limit_order_rests_and_partially_fills(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees, participation="0.1")
    order = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.LIMIT, D("3"), D("95"))))
    assert run(paper.get_balances())["USDT"].locked == D("285")
    paper.on_candle(market.symbol, candle(1, "100", "101", "96", "99", v="100"))  # low 96 > 95: no fill
    assert order.filled_qty == 0
    paper.on_candle(market.symbol, candle(2, "99", "99", "94", "95", v="10"))  # trades through: 1 unit
    assert order.filled_qty == D("1") and order.status is OrderStatus.PARTIALLY_FILLED
    assert order.fills[-1].is_maker and order.fee == D("0.001")  # maker fee 0.1 %
    paper.on_candle(market.symbol, candle(3, "95", "96", "90", "92", v="100"))
    assert order.status is OrderStatus.FILLED and order.filled_qty == D("3")
    bal = run(paper.get_balances())
    assert bal["USDT"].free == D("715") and bal["USDT"].locked == 0


def test_limit_touch_without_trade_through_does_not_fill(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees)
    order = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.LIMIT, D("1"), D("95"))))
    paper.on_candle(market.symbol, candle(1, "100", "100", "95", "99"))
    assert order.filled_qty == 0


def test_rejects_insufficient_balance_and_min_notional(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees, quote="50")
    o1 = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.MARKET, D("1"))))
    assert o1.status is OrderStatus.REJECTED and o1.reject_reason == "insufficient_balance"
    o2 = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.MARKET, D("0.01"))))
    assert o2.status is OrderStatus.REJECTED and o2.reject_reason == "below_min_notional"
    assert run(paper.get_balances())["USDT"].free == D("50")


def test_cancel_releases_reserve(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees)
    o = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.LIMIT, D("2"), D("90"))))
    run(paper.cancel_all())
    assert o.status is OrderStatus.CANCELED
    assert run(paper.get_balances())["USDT"].free == D("1000")
    assert run(paper.get_open_orders()) == []


def test_gap_up_never_overspends(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees, quote="1000")
    o = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.MARKET, D("9.8"))))
    paper.on_candle(market.symbol, candle(1, "150", "150", "150", "150"))  # +50 % gap
    bal = run(paper.get_balances())
    assert bal["USDT"].free >= 0 and bal["USDT"].locked == 0
    assert o.quote_filled <= D("1000")


def test_paper_clock_used_for_orders(market: Market, fees: FeeModel) -> None:
    paper, _ = make_paper(market, fees)
    o = run(paper.place_order(OrderRequest(market.symbol, Side.BUY, OrderType.MARKET, D("1"))))
    assert o.created_at == T0
