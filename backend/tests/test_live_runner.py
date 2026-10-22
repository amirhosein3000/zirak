"""Paper trading on live data (DATA_SOURCE=wallex) with a fake market-data client, plus the kill switch."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from zirak.config import SAMPLE_DATA_DIR, Settings
from zirak.data.store import load_candle_dir
from zirak.engine.risk import RiskConfig
from zirak.engine.runner import BotRunner
from zirak.exchange.replay import ReplayExchange
from zirak.models import Candle
from zirak.strategy.registry import build_strategy


class FakeLive(ReplayExchange):
    """Serves the sample candles as if they were live, releasing one more closed candle per call."""

    def __init__(self) -> None:
        super().__init__(load_candle_dir(SAMPLE_DATA_DIR))
        self.released = 200

    async def get_candles(
        self, symbol: str, resolution: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        self.released += 1
        return self.series(symbol, resolution)[: self.released]


def test_live_paper_runner_trades_on_new_candles_and_kills(tmp_path: Path) -> None:
    settings = replace(
        Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL", replay_dir=SAMPLE_DATA_DIR),
        data_source="wallex",
        live_poll_s=0.01,
        stale_data_s=1e9,  # the sample candles are old; staleness has its own tests below
    )
    live = FakeLive()
    runner = BotRunner(settings, ReplayExchange({}), live)

    async def scenario() -> dict[str, Any]:
        await runner.start(build_strategy("dca", {"every": 2}), RiskConfig(), "BTCTMN", "1h")
        assert runner.mode == "paper-live"
        await asyncio.sleep(0.6)
        st = await runner.status()
        await runner.kill("test")
        return st

    st = asyncio.run(scenario())
    assert st["bot"]["candles_seen"] > 3, "new live candles were not processed"
    assert any(e["decision"]["approved"] for e in st["log"]), "no approved trades"
    assert runner.bot is not None and runner.bot.stopped and runner.kill_engaged
    assert all(not o.status.is_open for o in runner.paper.all_orders())  # type: ignore[union-attr]
    # A paper fill happened against the (synthetic) order book, not on a candle.
    fills = [f for o in runner.paper.all_orders() for f in o.fills]  # type: ignore[union-attr]
    assert fills and all(isinstance(f.ts, datetime) for f in fills)
    assert max(f.ts for f in fills) - min(f.ts for f in fills) < timedelta(days=365)


def test_old_candles_and_bad_books_block_new_buys(tmp_path: Path) -> None:
    """With realistic staleness limits the old sample counts as stale: the bot logs but never buys."""
    settings = replace(
        Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL", replay_dir=SAMPLE_DATA_DIR),
        data_source="wallex",
        live_poll_s=0.01,
        stale_data_s=120,
    )
    runner = BotRunner(settings, ReplayExchange({}), FakeLive())

    async def scenario() -> dict[str, Any]:
        await runner.start(build_strategy("dca", {"every": 2}), RiskConfig(), "BTCTMN", "1h")
        await asyncio.sleep(0.4)
        st = await runner.status()
        await runner.kill("test")
        return st

    st = asyncio.run(scenario())
    assert st["data_stale"] and st["bot"]["data_stale"]
    assert st["log"], "signals should still be logged"
    assert all(not e["decision"]["approved"] for e in st["log"] if e["side"] == "buy")
    assert {e["decision"]["code"] for e in st["log"] if e["side"] == "buy"} == {"stale_data"}


def test_book_sanity() -> None:
    from decimal import Decimal as D

    from zirak.engine.runner import book_is_sane
    from zirak.models import BookLevel, OrderBook, utcnow

    def book(bid: str | None, ask: str | None) -> OrderBook:
        return OrderBook(
            "X",
            utcnow(),
            [BookLevel(D(bid), D(1))] if bid else [],
            [BookLevel(D(ask), D(1))] if ask else [],
        )

    assert book_is_sane(book("99", "100"))
    assert not book_is_sane(book("100", "100"))  # crossed / locked
    assert not book_is_sane(book(None, "100"))
    assert not book_is_sane(book("99", None))


class DeadFeed(FakeLive):
    """Market data that works at start, then every call fails (exchange or network down)."""

    dead = False

    async def get_order_book(self, symbol: str) -> Any:
        if self.dead:
            import httpx

            raise httpx.ConnectError("down")
        return await super().get_order_book(symbol)

    async def get_candles(
        self, symbol: str, resolution: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        if self.dead:
            import httpx

            raise httpx.ConnectError("down")
        return await super().get_candles(symbol, resolution, start, end)


def test_kill_switch_works_while_market_data_is_down(tmp_path: Path) -> None:
    settings = replace(
        Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL", replay_dir=SAMPLE_DATA_DIR),
        data_source="wallex",
        live_poll_s=0.01,
        stale_data_s=1e9,
    )
    live = DeadFeed()
    runner = BotRunner(settings, ReplayExchange({}), live)

    async def scenario() -> None:
        await runner.start(build_strategy("dca", {"every": 1}), RiskConfig(), "BTCTMN", "1h")
        await asyncio.sleep(0.2)
        live.dead = True
        await asyncio.sleep(0.1)
        assert runner.running and runner.error and "unavailable" in runner.error
        await asyncio.wait_for(runner.kill("test"), timeout=2)

    asyncio.run(scenario())
    assert runner.kill_engaged and runner.bot is not None and runner.bot.stopped
    assert not runner.running
    assert all(not o.status.is_open for o in runner.paper.all_orders())  # type: ignore[union-attr]


def test_kill_file_from_another_process_stops_the_loop(tmp_path: Path) -> None:
    settings = replace(
        Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL", replay_dir=SAMPLE_DATA_DIR),
        data_source="wallex",
        live_poll_s=0.01,
        stale_data_s=1e9,
    )
    runner = BotRunner(settings, ReplayExchange({}), FakeLive())

    async def scenario() -> None:
        await runner.start(build_strategy("dca", {"every": 1}), RiskConfig(), "BTCTMN", "1h")
        await asyncio.sleep(0.1)
        settings.kill_file.write_text("zirak kill")  # what `zirak kill` does from another terminal
        for _ in range(100):
            if not runner.running:
                break
            await asyncio.sleep(0.02)

    asyncio.run(scenario())
    assert not runner.running and runner.bot is not None and runner.bot.stopped and runner.bot.risk.killed
