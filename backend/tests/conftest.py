from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from zirak.config import Settings
from zirak.exchange.paper import PaperExchange
from zirak.exchange.replay import ReplayExchange
from zirak.fees import FeeModel
from zirak.markets import DEFAULT_MARKETS
from zirak.models import Candle, Market

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def candle(i: int, o: str, h: str, low: str, c: str, v: str = "100") -> Candle:
    return Candle(T0 + timedelta(hours=i), D(o), D(h), D(low), D(c), D(v))


def flat_candles(n: int, price: str = "100", volume: str = "1000") -> list[Candle]:
    return [candle(i, price, price, price, price, volume) for i in range(n)]


@pytest.fixture
def market() -> Market:
    """A simple USDT market with round numbers for readable maths."""
    return Market(
        "TESTUSDT",
        "TST",
        "USDT",
        price_step=D("0.01"),
        qty_step=D("0.001"),
        min_qty=D("0.001"),
        min_notional=D("5"),
    )


@pytest.fixture
def fees() -> FeeModel:
    return FeeModel(maker=D("0.001"), taker=D("0.002"))


def make_paper(
    market: Market,
    fees: FeeModel,
    quote: str = "1000",
    base: str = "0",
    slippage_bps: str = "0",
    participation: str = "1",
) -> tuple[PaperExchange, ReplayExchange]:
    replay = ReplayExchange({(market.symbol, "1h"): flat_candles(3)}, markets={market.symbol: market})
    paper = PaperExchange(
        replay,
        {market.symbol: market},
        fees,
        D(slippage_bps),
        {market.quote: D(quote), market.base: D(base)},
        D(participation),
        clock=lambda: T0,
    )
    paper.set_last_price(market.symbol, D("100"))
    return paper, replay


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(kill_file=tmp_path / "KILL", data_dir=tmp_path, db_path=tmp_path / "db.sqlite")


@pytest.fixture
def btc_tmn() -> Market:
    return DEFAULT_MARKETS["BTCTMN"]
