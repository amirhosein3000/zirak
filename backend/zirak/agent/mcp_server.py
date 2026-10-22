"""Zirak MCP server: lets any MCP-capable AI agent (Claude Desktop, IDE agents, ...) inspect markets the
way Zirak sees them and audit the trading agent's runs. Read-only by design: there is no order tool.

    zirak mcp            # stdio transport

Tools: market_snapshot, list_runs, run_report, recent_decisions, explain_decision, verify, model_card.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from zirak.agent.config import AgentConfig
from zirak.agent.features import feature_frame, implied_closes
from zirak.agent.journal import Journal
from zirak.agent.report import build_report
from zirak.agent.tools import SNAPSHOT_FIELDS
from zirak.agent.verify import verify_run
from zirak.config import Settings, load_settings


def _runs_dir(s: Settings) -> Path:
    return s.data_dir / "runs"


def _run(s: Settings, name: str | None) -> Path:
    runs = _runs_dir(s)
    if name:
        path = runs / Path(name).name  # no path traversal: names only
    else:
        cands = sorted(
            (p for p in runs.glob("*") if (p / "manifest.json").exists()), key=lambda p: p.stat().st_mtime
        )
        if not cands:
            raise ValueError("no runs yet")
        path = cands[-1]
    if not (path / "manifest.json").exists():
        raise ValueError(f"unknown run {name}")
    return path


def build_server(settings: Settings | None = None) -> FastMCP:
    s = settings or load_settings()
    mcp = FastMCP("zirak")

    @mcp.tool()
    async def market_snapshot(symbol: str, resolution: str = "1h") -> dict[str, Any]:
        """Trend, momentum, volatility and Toman cross-rate gap of a market, from Zirak's feature engine."""
        from zirak.data.source import build_replay
        from zirak.exchange.wallex import WallexClient

        if s.data_source == "wallex":
            from datetime import timedelta

            from zirak.models import utcnow

            c = WallexClient(s)
            try:
                names = [symbol, "USDTTMN"] + ([f"{symbol[:-3]}USDT"] if symbol.endswith("TMN") else [])
                series = {
                    n: await c.get_candles(n, resolution, utcnow() - timedelta(days=15), utcnow())
                    for n in names
                }
            finally:
                await c.close()
        else:
            replay, _ = build_replay(s)
            series = {n: replay.series(n, resolution) for n in replay.markets}
        candles = series.get(symbol) or []
        if len(candles) < 30:
            return {"error": f"not enough {resolution} data for {symbol}"}
        df = feature_frame(candles, implied_closes(series, symbol))
        r = df.iloc[-1]
        out = {"symbol": symbol, "ts": str(r["ts"]), "close": float(r["close"])}
        for k in SNAPSHOT_FIELDS:
            v = float(r[k])
            out[k] = None if math.isnan(v) else round(v, 4)
        return out

    @mcp.tool()
    def list_runs() -> list[dict[str, Any]]:
        """The agent's runs (backtest / shadow / live) with their mode and start time."""
        out = []
        for p in sorted(_runs_dir(s).glob("*")):
            mf = p / "manifest.json"
            if mf.exists():
                m = json.loads(mf.read_text(encoding="utf-8"))
                out.append(
                    {"run": p.name, "mode": m.get("mode"), "start": m.get("start"), "commit": m.get("commit")}
                )
        return out

    @mcp.tool()
    def run_report(run: str | None = None) -> dict[str, Any]:
        """Judge metrics of a run: return, drawdown, trades, volume, activity per day, speed, errors, AI stats."""
        path = _run(s, run)
        m = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        return build_report(path, AgentConfig.model_validate(m["config"]), m["mode"])

    @mcp.tool()
    def recent_decisions(
        run: str | None = None, limit: int = 20, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """The latest decision records (candidates taken or skipped and why, exits, guard changes)."""
        rows = Journal(_run(s, run)).read("decisions.jsonl")
        if kind:
            rows = [d for d in rows if d.get("kind") == kind]
        return [{k: v for k, v in d.items() if k != "features"} for d in rows[-max(1, min(limit, 200)) :]]

    @mcp.tool()
    def explain_decision(decision_id: str, run: str | None = None) -> dict[str, Any]:
        """One decision in full (signal, model inputs and verdict, posture, risk sizing) plus its outcome."""
        rows = Journal(_run(s, run)).read("decisions.jsonl")
        main = next((d for d in rows if d.get("id") == decision_id), None)
        if main is None:
            return {"error": f"no decision {decision_id}"}
        return {"decision": main, "follow_ups": [d for d in rows if d.get("ref") == decision_id]}

    @mcp.tool()
    def verify(run: str | None = None) -> dict[str, Any]:
        """Recompute every AI verdict of a run from its logged inputs and saved models."""
        return verify_run(_run(s, run))

    @mcp.tool()
    def model_card(run: str | None = None) -> list[dict[str, Any]]:
        """The ML meta-labeler(s) a run used: training window, holdout AUC, EV of taken trades."""
        path = _run(s, run) / "models"
        return [
            json.loads((p / "model_card.json").read_text(encoding="utf-8"))
            for p in sorted(path.glob("*"))
            if (p / "model_card.json").exists()
        ]

    return mcp
