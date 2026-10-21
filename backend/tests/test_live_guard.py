"""Safety: with LIVE_TRADING=false nothing can reach a real order endpoint."""

import ast
import asyncio
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from zirak.config import Settings
from zirak.engine.executor import Executor
from zirak.engine.risk import RiskDecision
from zirak.exchange.guard import (
    HardLimitExceeded,
    LiveTradingDisabled,
    check_hard_limits,
    live_blockers,
    require_live,
)
from zirak.exchange.wallex import WallexClient
from zirak.models import Market, OrderRequest, OrderType, Side
from zirak.strategy.base import Signal

PKG = Path(__file__).resolve().parents[1] / "zirak"


def live_settings(tmp: Path) -> Settings:
    return Settings(
        live_trading=True,
        max_order_tmn=D("1000000"),
        max_order_usdt=D("20"),
        daily_loss_limit_pct=D("2"),
        wallex_api_key="test-key",
        kill_file=tmp / "KILL",
    )


def test_default_settings_block_live(settings: Settings) -> None:
    assert not settings.live_trading
    assert "LIVE_TRADING is not true" in live_blockers(settings)
    with pytest.raises(LiveTradingDisabled):
        require_live(settings)


@pytest.mark.parametrize(
    "field,value",
    [
        ("live_trading", False),
        ("max_order_tmn", None),
        ("max_order_usdt", None),
        ("daily_loss_limit_pct", None),
        ("wallex_api_key", None),
    ],
)
def test_every_condition_is_required(tmp_path: Path, field: str, value: Any) -> None:
    s = live_settings(tmp_path)
    require_live(s)  # all set: allowed
    with pytest.raises(LiveTradingDisabled):
        require_live(replace(s, **{field: value}))


def test_kill_file_blocks_new_orders_but_not_cancels(tmp_path: Path) -> None:
    s = live_settings(tmp_path)
    s.kill_file.write_text("x")
    with pytest.raises(LiveTradingDisabled):
        require_live(s)
    require_live(s, risk_reducing=True)  # cancels must still work


def test_wallex_client_order_methods_guarded_before_anything(settings: Settings) -> None:
    client = WallexClient(settings)
    req = OrderRequest("BTCTMN", Side.BUY, OrderType.MARKET, D("0.001"))
    for coro in (
        client.place_order(req),
        client.cancel_order("BTCTMN", "1"),
        client.get_open_orders(),
        client.get_balances(),
        client.get_order("BTCTMN", "1"),
        client.cancel_all(),
    ):
        with pytest.raises(LiveTradingDisabled):
            asyncio.run(coro)


def test_executor_refuses_real_exchange_when_not_live(settings: Settings, btc_tmn: Market) -> None:
    ex = Executor(WallexClient(settings), btc_tmn, settings)
    sig = Signal(Side.BUY, D("10"), "t", "t")
    with pytest.raises(LiveTradingDisabled):
        asyncio.run(ex.execute(sig, RiskDecision(True, D("0.001"), "ok"), D("1000000000"), "t"))


def test_hard_cap(tmp_path: Path, btc_tmn: Market) -> None:
    s = live_settings(tmp_path)
    ok = OrderRequest("BTCTMN", Side.BUY, OrderType.MARKET, D("0.0001"))
    check_hard_limits(s, btc_tmn, ok, D("5000000000"))  # 500,000 TMN < 1,000,000 cap
    too_big = OrderRequest("BTCTMN", Side.BUY, OrderType.MARKET, D("0.001"))
    with pytest.raises(HardLimitExceeded):
        check_hard_limits(s, btc_tmn, too_big, D("5000000000"))  # 5,000,000 TMN


def test_no_withdraw_or_transfer_code_exists() -> None:
    banned = ("withdraw", "transfer")
    for path in PKG.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = getattr(node, "name", None) or getattr(node, "attr", None) or getattr(node, "id", None)
            if isinstance(name, str):
                assert not any(b in name.lower() for b in banned), f"{path.name}: {name}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/"):
                assert not any(b in node.value.lower() for b in banned), f"{path.name}: {node.value}"


def test_only_wallex_client_is_real() -> None:
    from zirak.exchange.paper import PaperExchange
    from zirak.exchange.replay import ReplayExchange

    assert WallexClient.is_real and not PaperExchange.is_real and not ReplayExchange.is_real
