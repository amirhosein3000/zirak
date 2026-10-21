from decimal import Decimal as D

from zirak.fees import FeeModel, apply_slippage, fill_amounts, round_trip_cost_pct
from zirak.models import Market, Side, ceil_to_step, floor_to_step


def test_slippage_moves_price_against_us(market: Market) -> None:
    assert apply_slippage(D("100"), Side.BUY, D("10"), market) == D("100.10")
    assert apply_slippage(D("100"), Side.SELL, D("10"), market) == D("99.90")


def test_slippage_rounds_to_tick_against_us(market: Market) -> None:
    # 100 * 1.0003 = 100.03 exactly; 100.001 * 1.0001 = 100.0110001 -> buy rounds UP to 100.02
    assert apply_slippage(D("100.001"), Side.BUY, D("1"), market) == D("100.02")
    # sell: 100.019 * 0.9999 = 100.0089981 -> rounds DOWN to 100.00
    assert apply_slippage(D("100.019"), Side.SELL, D("1"), market) == D("100.00")


def test_zero_slippage_is_identity(market: Market) -> None:
    assert apply_slippage(D("123.45"), Side.BUY, D("0"), market) == D("123.45")


def test_buy_fee_taken_in_base(market: Market) -> None:
    a = fill_amounts(market, Side.BUY, D("100"), D("2"), D("0.002"))
    assert a.quote_delta == D("-200")
    assert a.base_delta == D("1.996")
    assert a.fee == D("0.004") and a.fee_asset == "TST"


def test_sell_fee_taken_in_quote(market: Market) -> None:
    a = fill_amounts(market, Side.SELL, D("100"), D("2"), D("0.002"))
    assert a.base_delta == D("-2")
    assert a.quote_delta == D("199.6")
    assert a.fee == D("0.4") and a.fee_asset == "USDT"


def test_round_trip_cost() -> None:
    assert round_trip_cost_pct(FeeModel(D("0.001"), D("0.0025")), D("5")) == D("0.6")


def test_step_rounding() -> None:
    assert floor_to_step(D("1.23456"), D("0.001")) == D("1.234")
    assert ceil_to_step(D("1.23401"), D("0.001")) == D("1.235")
    assert floor_to_step(D("12345"), D("100")) == D("12300")


def test_market_order_checks(market: Market) -> None:
    assert market.check_order(D("0.0001"), D("100")) == "qty_precision"
    assert market.check_order(D("0.01"), D("100")) == "below_min_notional"  # 1 USDT < 5
    assert market.check_order(D("0.05"), D("100")) is None
    assert market.check_order(D("0"), D("100")) == "qty_not_positive"
