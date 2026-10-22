"""The agent's tools: what the LLM posture agent (and the MCP server) can look at. All read-only.

Each tool is an async function taking a dict of arguments and returning JSON-able data. Market data
comes from the exchange client the agent already uses (Wallex REST, or the replay in tests). If the
organisers' Wallex MCP is attached later, its read-only market tools can be added here the same way;
order placement never goes through a tool.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from zirak.exchange.base import ExchangeClient

if TYPE_CHECKING:
    from zirak.agent.engine import Agent

ToolFn = Callable[[dict[str, Any]], Awaitable[Any]]

SNAPSHOT_FIELDS = (
    "ret_1", "ret_4", "ret_16", "ret_96", "rsi_14", "bb_pctb", "atr_pct", "atr_ratio", "ema50_gap",
    "ema200_gap", "ema50_slope", "efficiency_48", "vol_z", "basis_pct", "basis_dev", "catchup_4",
)  # fmt: skip


def _clean(x: Any) -> Any:
    if isinstance(x, float):
        return None if math.isnan(x) else round(x, 4)
    return x


def make_tools(agent: Agent, data: ExchangeClient) -> dict[str, ToolFn]:
    async def get_market_snapshot(args: dict[str, Any]) -> dict[str, Any]:
        sym = str(args.get("symbol", ""))
        df = agent.frames.get(sym)
        if df is None or df.empty:
            return {"error": f"no data for {sym}"}
        r = df.iloc[-1]
        out: dict[str, Any] = {"symbol": sym, "ts": str(r["ts"]), "close": float(r["close"])}
        out.update({k: _clean(float(r[k])) for k in SNAPSHOT_FIELDS if k in df})
        try:
            book = await data.get_order_book(sym)
            bid, ask = book.best_bid, book.best_ask
            if bid and ask:
                mid = (bid + ask) / 2
                near_b = sum(float(lv.qty) for lv in book.bids if lv.price >= mid * 99 / 100)
                near_a = sum(float(lv.qty) for lv in book.asks if lv.price <= mid * 101 / 100)
                out["spread_pct"] = round(float((ask - bid) / mid * 100), 4)
                out["book_imbalance_pct"] = (
                    round((near_b - near_a) / (near_b + near_a) * 100, 1) if near_b + near_a else None
                )
        except Exception as e:  # the agent can still decide without the book
            out["book_error"] = type(e).__name__
        pos = agent.positions.get(sym)
        out["in_position"] = pos is not None
        return out

    async def get_portfolio(args: dict[str, Any]) -> dict[str, Any]:
        g = agent.guard
        eq = agent.equity_now
        return {
            "equity_tmn": float(eq),
            "peak_tmn": float(g.peak),
            "drawdown_pct": round(float((g.peak - eq) / g.peak * 100), 3) if g.peak > 0 else 0.0,
            "today_pnl_pct": round(float((eq - g.day_start) / g.day_start * 100), 3)
            if g.day_start > 0
            else 0.0,
            "guard": g.last_status,
            "positions": [
                {
                    "symbol": p.symbol,
                    "setup": p.setup,
                    "entry": float(p.entry_price),
                    "stop": float(p.stop),
                    "take_profit": float(p.take_profit),
                    "bars": p.bars,
                }
                for p in agent.positions.values()
            ],
            "errors": agent.errors,
        }

    async def get_recent_decisions(args: dict[str, Any]) -> list[dict[str, Any]]:
        n = max(1, min(int(args.get("limit", 10) or 10), 30))
        rows = [d for d in agent.journal.read("decisions.jsonl") if d.get("kind") in ("candidate", "exit")][
            -n:
        ]
        return [
            {k: d.get(k) for k in ("ts", "kind", "symbol", "setup", "action", "exit", "pnl_pct")}
            | {"prob": (d.get("model") or {}).get("prob")}
            for d in rows
        ]

    async def get_model_stats(args: dict[str, Any]) -> dict[str, Any]:
        return agent.model.card.to_dict()

    return {
        "get_market_snapshot": get_market_snapshot,
        "get_portfolio": get_portfolio,
        "get_recent_decisions": get_recent_decisions,
        "get_model_stats": get_model_stats,
    }
