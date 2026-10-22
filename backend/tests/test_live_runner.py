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
