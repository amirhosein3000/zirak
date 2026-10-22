"""The LLM posture agent: an agentic layer that decides *how much risk* each market deserves right now.

Every `interval` (default 1 h) the agent runs a short tool-calling loop. It can look at market snapshots
(trend, volatility, cross-rate gap), the portfolio, recent decisions and the ML model's track record, then
returns, per market:

    stance          normal | cautious | avoid
    risk_multiplier 0 .. 1.5   (scales the ML-sized position; still capped by the hard limits)
    allowed_setups  which setup families may open trades here
    reason_fa       one Persian sentence

Authority is bounded on purpose: the agent can pause a market, shrink or moderately enlarge risk and
switch setups, but it never places orders, never touches the stops and can never exceed the hard caps
in portfolio.py. Every posture (with its tool calls) is written to the run's `postures.jsonl`; replays
read it back instead of calling the LLM, so runs are reproducible.

Without an LLM (MOCK_LLM, no key, or the call fails) a deterministic rule posture is used and labelled
`source="rules"`, so the record always says which brain decided.
"""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from zirak.agent.setups import SETUPS
from zirak.llm.provider import ToolLLM

STANCES = ("normal", "cautious", "avoid")
MAX_MULT = 1.5
MAX_STEPS = 6


@dataclass
class MarketPosture:
    stance: str = "normal"
    risk_multiplier: float = 1.0
    allowed_setups: list[str] = field(default_factory=lambda: list(SETUPS))
    reason_fa: str = ""

    def allows(self, setup: str) -> bool:
        return self.stance != "avoid" and self.risk_multiplier > 0 and setup in self.allowed_setups


@dataclass
class Posture:
    ts: str
    source: str  # "llm:<model>" | "rules" | "replay"
    markets: dict[str, MarketPosture]
    summary_fa: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def for_market(self, symbol: str) -> MarketPosture:
        return self.markets.get(symbol) or MarketPosture(reason_fa="بدون نظر عامل؛ حالت عادی")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Posture:
        return cls(
            d["ts"],
            d["source"],
            {k: MarketPosture(**v) for k, v in d["markets"].items()},
            d.get("summary_fa", ""),
            d.get("tool_calls", []),
        )


# ---- deterministic fallback --------------------------------------------------------------------
def rule_posture(ts: datetime, frames: dict[str, pd.DataFrame]) -> Posture:
    """Regime rules from the latest closed candle of each market (used when no LLM answers)."""
    markets: dict[str, MarketPosture] = {}
    for sym, df in frames.items():
        if df.empty:
            continue
        r = df.iloc[-1]
        eff, slope, atr_ratio = (_f(r.get(k)) for k in ("efficiency_48", "ema50_slope", "atr_ratio"))
        if atr_ratio is not None and atr_ratio >= 2.0:
            markets[sym] = MarketPosture(
                "cautious",
                0.5,
                ["mean_reversion", "basis_reversion"],
                "نوسان بیش از دو برابر حالت عادی است؛ حجم نصف و فقط ورودهای بازگشتی.",
            )
        elif eff is not None and slope is not None and eff >= 0.3 and slope < -0.3:
            markets[sym] = MarketPosture(
                "cautious",
                0.5,
                ["mean_reversion", "basis_reversion"],
                "روند نزولی منظم است؛ شکست سقف و ورود روندی ممنوع و حجم نصف.",
            )
        elif eff is not None and slope is not None and eff >= 0.3 and slope > 0.3:
            markets[sym] = MarketPosture(
                "normal",
                1.0,
                ["breakout", "trend_pullback", "mean_reversion", "basis_reversion"],
                "روند صعودی منظم است؛ همهٔ الگوها مجازند.",
            )
        else:
            markets[sym] = MarketPosture(
                "normal",
                1.0,
                ["mean_reversion", "basis_reversion", "breakout"],
                "بازار رنج یا بدون روند روشن است؛ الگوهای بازگشتی در اولویت‌اند.",
            )
    return Posture(
        ts.isoformat(), "rules", markets, "حالت بازارها با قواعد ثابت رژیم تعیین شد (بدون مدل زبانی)."
    )


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


# ---- LLM agent ---------------------------------------------------------------------------------
ToolFn = Callable[[dict[str, Any]], Awaitable[Any]]

SYSTEM = f"""You are the risk-posture agent of Zirak, an automated spot trading engine on the Wallex exchange
(Toman markets, 3-day competition, long-only, profit must be realised in Toman).
A deterministic engine finds trade candidates with explainable setups ({", ".join(SETUPS)}), an ML model
estimates each candidate's win probability after fees, and hard risk limits size and protect every trade.
YOUR job: for each market, decide the risk posture for the next hour.
- Use the tools to inspect each market (and the portfolio / recent decisions / model stats if useful).
- stance: "normal" | "cautious" | "avoid". risk_multiplier: 0 to {MAX_MULT} (1 = as the model sized it).
- allowed_setups: subset of {list(SETUPS)} that may open trades in that market now.
- Be conservative after losses, in falling or chaotic markets, and when the model's record is weak.
- You never place orders and cannot change stops; the hard limits always apply.
Reply with ONLY JSON:
{{"markets": {{"<SYMBOL>": {{"stance": "...", "risk_multiplier": 1.0, "allowed_setups": ["..."],
"reason_fa": "<one Persian sentence>"}}}}, "summary_fa": "<one or two Persian sentences>"}}"""


def tool_specs(markets: list[str]) -> list[dict[str, Any]]:
    def fn(
        name: str, desc: str, params: dict[str, Any] | None = None, required: list[str] | None = None
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {"type": "object", "properties": params or {}, "required": required or []},
            },
        }

    sym = {"symbol": {"type": "string", "enum": markets}}
    return [
        fn(
            "get_market_snapshot",
            "Trend, momentum, volatility, cross-rate gap and order book of one market.",
            sym,
            ["symbol"],
        ),
        fn("get_portfolio", "Equity, cash, open positions, drawdown, today's P&L and trade count."),
        fn(
            "get_recent_decisions",
            "The last decisions of the engine (taken and skipped) with outcomes.",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        ),
        fn(
            "get_model_stats", "The ML meta-labeler's model card: holdout AUC, EV of taken trades, win rates."
        ),
    ]


class PostureAgent:
    def __init__(self, llm: ToolLLM, tools: dict[str, ToolFn], markets: list[str]) -> None:
        self.llm = llm
        self.tools = tools
        self.markets = markets

    async def decide(self, now: datetime, frames: dict[str, pd.DataFrame]) -> Posture:
        fallback = rule_posture(now, frames)
        if getattr(self.llm, "name", "mock") == "mock":
            return fallback
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": f"Time (UTC): {now.isoformat()}. Markets: {', '.join(self.markets)}.",
            },
        ]
        calls: list[dict[str, Any]] = []
        for _ in range(MAX_STEPS):
            msg = await self.llm.chat_tools(messages, tool_specs(self.markets))
            if msg is None:
                break
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                parsed = parse_posture(msg.get("content") or "", self.markets)
                if parsed is None:
                    break
                markets, summary = parsed
                for sym, mp in fallback.markets.items():
                    markets.setdefault(sym, mp)  # a market the LLM forgot keeps the rule posture
                model = getattr(self.llm, "model", self.llm.name)
                return Posture(now.isoformat(), f"llm:{model}", markets, summary, calls)
            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc.get("function", {}).get("name", "")
                try:
                    args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                fn = self.tools.get(name)
                result = await fn(args) if fn else {"error": f"unknown tool {name}"}
                calls.append({"name": name, "args": args})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", name),
                        "content": json.dumps(result, default=str),
                    }
                )
        fallback.summary_fa += " (مدل زبانی پاسخ معتبر نداد؛ قواعد ثابت به کار رفت.)"
        fallback.tool_calls = calls
        return fallback


def parse_posture(text: str, markets: list[str]) -> tuple[dict[str, MarketPosture], str] | None:
    """Validate and clamp the LLM's JSON. Unknown markets, stances or setups are dropped, never trusted."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict) or not isinstance(data.get("markets"), dict):
        return None
    out: dict[str, MarketPosture] = {}
    for sym, v in data["markets"].items():
        if sym not in markets or not isinstance(v, dict):
            continue
        stance = str(v.get("stance")) if v.get("stance") in STANCES else "cautious"
        mult = _f(v.get("risk_multiplier"))
        mult = 0.5 if mult is None else min(max(mult, 0.0), MAX_MULT)
        if stance == "avoid":
            mult = 0.0
        setups = [s for s in v.get("allowed_setups") or [] if s in SETUPS]
        reason = str(v.get("reason_fa") or "")[:400]
        out[sym] = MarketPosture(stance, round(mult, 3), setups, reason)
    return out, str(data.get("summary_fa") or "")[:600]
