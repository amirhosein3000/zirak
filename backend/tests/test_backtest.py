from decimal import Decimal as D

import pytest

from tests.conftest import candle
from zirak.backtest.engine import BacktestSetup, run_backtest
from zirak.backtest.metrics import max_drawdown_pct
from zirak.config import SAMPLE_DATA_DIR
from zirak.data.store import load_candle_dir
from zirak.engine.risk import RiskConfig
from zirak.fees import FeeModel
from zirak.markets import DEFAULT_MARKETS
from zirak.models import Candle, Market, Side
from zirak.strategy.base import Signal, Strategy, StrategyContext
from zirak.strategy.registry import build_strategy


class BuyOnce(Strategy):
    key = "buy_once"

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        return [] if ctx.in_position or ctx.entries else [Signal(Side.BUY, D("100"), "t", "t")]


class Peeker(Strategy):
    """Fails the test if it ever sees a candle that has not closed yet."""

    key = "peeker"

    def __init__(self, candles: list[Candle]) -> None:
        super().__init__()
        self.candles = candles

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        last_seen = ctx.df["ts"].iloc[-1]
        assert last_seen + (self.candles[1].ts - self.candles[0].ts) <= ctx.now
        return []


def setup_for(
    market: Market, strat: Strategy, risk: RiskConfig | None = None, fee: str = "0.002", slip: str = "0"
) -> BacktestSetup:
    return BacktestSetup(
        market,
        "1h",
        strat,
        risk or RiskConfig(stop_loss_pct=None, daily_loss_limit_pct=None, max_position_pct=D("100")),
        FeeModel(D(fee), D(fee)),
        D(slip),
        D("1000"),
        D("1"),
    )


def rising(n: int = 20) -> list[Candle]:
    return [candle(i, str(100 + i), str(101 + i), str(99 + i), str(100 + i), "10000") for i in range(n)]


def test_buy_fills_at_next_open_not_signal_close(market: Market) -> None:
    report = run_backtest(rising(), setup_for(market, BuyOnce()))
    buy = report["trades"][0]
    assert buy["side"] == "buy"
    # signal on candle 0 (close 100) -> filled at candle 1's open (101)
    assert D(buy["avg_price"]) == D("101")


def test_fees_reduce_returns(market: Market) -> None:
    free = run_backtest(rising(), setup_for(market, BuyOnce(), fee="0"))["metrics"]["return_pct"]
    paid = run_backtest(rising(), setup_for(market, BuyOnce(), fee="0.01"))["metrics"]["return_pct"]
    assert paid < free


def test_no_lookahead(market: Market) -> None:
    candles = rising(30)
    run_backtest(candles, setup_for(market, Peeker(candles)))


def test_max_drawdown() -> None:
    assert max_drawdown_pct([100, 120, 90, 130, 117]) == pytest.approx(-25.0)
    assert max_drawdown_pct([100, 110, 120]) == 0.0


@pytest.mark.parametrize("key", ["ema_cross", "rsi_reversion", "grid", "dca"])
def test_baselines_run_on_sample(key: str) -> None:
    data = load_candle_dir(SAMPLE_DATA_DIR)
    series = data[("BTCTMN", "1h")]
    setup = BacktestSetup(
        DEFAULT_MARKETS["BTCTMN"],
        "1h",
        build_strategy(key),
        RiskConfig(),
        FeeModel(D("0.002"), D("0.0025")),
        D("5"),
        D("100000000"),
    )
    report = run_backtest(series, setup)
    m = report["metrics"]
    assert m["orders"] > 0, f"{key} never traded"
    assert m["max_drawdown_pct"] <= 0
    assert m["fees_paid_quote"] > 0
    assert len(report["equity_curve"]) <= 801
    # Balances never go negative: final equity is positive.
    assert m["end_equity"] > 0


class BuyThenSell(Strategy):
    key = "buy_then_sell"

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        if len(ctx.df) == 2:
            return [Signal(Side.BUY, D("33.3"), "t", "t")]  # odd size -> fee leaves sub-step dust
        if len(ctx.df) == 5 and ctx.in_position:
            return [Signal(Side.SELL, D("100"), "t", "t")]
        return []


def test_full_exit_leaves_ledger_flat(market: Market) -> None:
    report = run_backtest(rising(12), setup_for(market, BuyThenSell()))
    sides = [t["side"] for t in report["trades"]]
    assert sides == ["buy", "sell"]
    assert D(report["open_position_qty"]) == 0
    assert report["metrics"]["exposure_pct"] < 50
    assert all(t["reason"] != "stop_loss" for t in report["trades"])


class AlwaysBuy(Strategy):
    key = "always_buy"

    def on_candle(self, ctx: StrategyContext) -> list[Signal]:
        return [Signal(Side.BUY, D("20"), "dip", "buy")]


def test_daily_loss_limit_halts_the_whole_pipeline(market: Market) -> None:
    """End to end: once today's loss crosses the limit the bot flattens and places no new buys today."""
    prices = [100, 100, 100, 90, 80, 75, 75, 75, 75, 75]  # all within one UTC day (hourly candles)
    candles = [candle(i, str(p), str(p), str(p), str(p), "100000") for i, p in enumerate(prices)]
    risk = RiskConfig(stop_loss_pct=None, daily_loss_limit_pct=D("3"), max_position_pct=D("100"))
    report = run_backtest(candles, setup_for(market, AlwaysBuy(), risk))
    trades = report["trades"]
    halt = next(i for i, t in enumerate(trades) if t["reason"] == "daily_loss_limit")
    assert trades[halt]["side"] == "sell" and trades[halt]["decision"]["approved"]
    later_buys = [t for t in trades[halt + 1 :] if t["side"] == "buy"]
    assert later_buys and all(not t["decision"]["approved"] for t in later_buys)
    assert {t["decision"]["code"] for t in later_buys} == {"daily_loss_limit"}
    assert D(report["open_position_qty"]) == 0
