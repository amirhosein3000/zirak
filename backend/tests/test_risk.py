from datetime import timedelta
from decimal import Decimal as D

from tests.conftest import T0
from zirak.engine.risk import PortfolioView, RiskConfig, RiskManager
from zirak.models import HUNDRED, Market, Side
from zirak.strategy.base import Signal

BUY = Signal(Side.BUY, D("50"), "test", "تست")
SELL_ALL = Signal(Side.SELL, HUNDRED, "test", "تست")


def view(
    equity: str = "1000",
    price: str = "100",
    qty: str = "0",
    avg: str | None = None,
    quote_free: str | None = None,
    hours: int = 0,
) -> PortfolioView:
    return PortfolioView(
        now=T0 + timedelta(hours=hours),
        price=D(price),
        position_qty=D(qty),
        avg_entry=D(avg) if avg else None,
        equity=D(equity),
        quote_free=D(quote_free if quote_free is not None else equity),
        base_free=D(qty),
    )


def rm(market: Market, **cfg: object) -> RiskManager:
    return RiskManager(RiskConfig.from_dict(dict(cfg)), market, cost_buffer=D("0"))


def test_buy_sized_by_equity_pct(market: Market) -> None:
    d = rm(market, max_position_pct=100).review(BUY, view())
    assert d.approved and d.qty == D("5")  # 50 % of 1000 at price 100


def test_max_exposure_caps_and_blocks(market: Market) -> None:
    r = rm(market, max_position_pct=30)
    d = r.review(BUY, view())
    assert d.approved and d.qty == D("3") and d.notes_fa
    blocked = r.review(BUY, view(qty="3", quote_free="700"))
    assert not blocked.approved and blocked.code == "max_exposure"


def test_per_order_cap(market: Market) -> None:
    d = rm(market, max_position_pct=100, max_order_quote=120).review(BUY, view())
    assert d.approved and d.qty == D("1.2")


def test_cost_buffer_keeps_quote_for_fees(market: Market) -> None:
    r = RiskManager(RiskConfig(max_position_pct=D("100")), market, cost_buffer=D("0.01"))
    d = r.review(Signal(Side.BUY, HUNDRED, "t", "t"), view())
    assert d.approved and d.qty * D("100") <= D("1000") / D("1.01")


def test_below_min_notional_rejected(market: Market) -> None:
    d = rm(market).review(Signal(Side.BUY, D("0.1"), "t", "t"), view())  # 1 USDT < 5 minimum
    assert not d.approved and d.code == "below_min_notional"


def test_stop_loss_and_take_profit(market: Market) -> None:
    r = rm(market, stop_loss_pct=5, take_profit_pct=10)
    assert r.exit_signals(view(price="96", qty="1", avg="100")) == []
    sl = r.exit_signals(view(price="95", qty="1", avg="100"))
    assert sl and sl[0].reason == "stop_loss" and sl[0].side is Side.SELL
    tp = r.exit_signals(view(price="110", qty="1", avg="100"))
    assert tp and tp[0].reason == "take_profit"


def test_daily_loss_limit_halts_buys_and_flattens(market: Market) -> None:
    r = rm(market, daily_loss_limit_pct=3)
    assert r.on_candle(view(equity="1000")) == []
    assert r.on_candle(view(equity="980", qty="1", hours=1)) == []  # -2 %: fine
    flatten = r.on_candle(view(equity="969", qty="1", hours=2))  # -3.1 %: halt
    assert r.halted and flatten and flatten[0].reason == "daily_loss_limit"
    d = r.review(BUY, view(equity="969", hours=2))
    assert not d.approved and d.code == "daily_loss_limit"
    # Selling is still allowed while halted.
    assert r.review(SELL_ALL, view(equity="969", qty="1", hours=2)).approved
    # Next UTC day: trading resumes.
    r.on_candle(view(equity="969", hours=30))
    assert not r.halted and r.review(BUY, view(equity="969", hours=30)).approved


def test_kill_blocks_buys_forever_but_allows_sells(market: Market) -> None:
    r = rm(market)
    r.kill()
    r.on_candle(view(hours=48))  # a new day does not un-kill
    assert r.halted and not r.review(BUY, view(hours=48)).approved
    assert r.review(SELL_ALL, view(qty="1", hours=48)).approved


def test_cooldown_after_exit(market: Market) -> None:
    r = rm(market, cooldown_candles=2)
    r.on_candle(view())
    r.on_exit()
    r.on_candle(view(hours=1))
    assert r.review(BUY, view(hours=1)).code == "cooldown"
    r.on_candle(view(hours=2))
    assert r.review(BUY, view(hours=2)).code == "cooldown"
    r.on_candle(view(hours=3))
    assert r.review(BUY, view(hours=3)).approved


def test_sell_leaves_no_dust(market: Market) -> None:
    # Selling 99 % would leave 0.01 units = 1 USDT < 5 minimum, so it sells everything.
    d = rm(market).review(Signal(Side.SELL, D("99"), "t", "t"), view(qty="1"))
    assert d.approved and d.qty == D("1")
