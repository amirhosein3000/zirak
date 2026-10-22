"""Run report in the judges' terms: return, drawdown, number of trades, volume, average trade volume,
activity per day, speed (latency), stability (errors), and what the AI decided (taken / skipped and why).
Built only from a run's journal files, so anyone can rebuild it: `zirak agent report <run_dir>`.
"""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from zirak.agent.config import AgentConfig
from zirak.agent.journal import Journal


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 1)


def build_report(run_dir: Path, cfg: AgentConfig, mode: str) -> dict[str, Any]:
    j = Journal(run_dir)
    trades = j.read("trades.jsonl")
    decisions = j.read("decisions.jsonl")
    orders = j.read("orders.jsonl")
    bars = j.read("bars.jsonl")
    eq_rows: list[dict[str, str]] = []
    eq_path = run_dir / "equity.csv"
    if eq_path.exists():
        with eq_path.open(encoding="utf-8") as f:
            eq_rows = list(csv.DictReader(f))
    equity = [float(r["equity_tmn"]) for r in eq_rows]
    start = equity[0] if equity else cfg.initial_equity_tmn
    end = equity[-1] if equity else start
    peak, max_dd = start, 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak * 100 if peak > 0 else 0.0)
    pnl = [float(t["pnl_tmn"]) for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    volume = sum(float(t["cost_tmn"]) + float(t["proceeds_tmn"]) for t in trades)
    per_day: dict[str, int] = defaultdict(int)
    for t in trades:
        per_day[str(t["closed_at"])[:10]] += 1
    cands = [d for d in decisions if d.get("kind") == "candidate"]
    taken = [d for d in cands if d.get("action") == "buy"]
    skip_model = [
        d for d in cands if d.get("action") == "skip" and str(d.get("reason_fa", "")).startswith("مدل")
    ]
    skip_posture = [
        d for d in cands if d.get("action") == "skip" and str(d.get("reason_fa", "")).startswith("عامل")
    ]
    by_setup: dict[str, dict[str, float]] = {}
    for setup in sorted({t["setup"] for t in trades}):
        sp = [float(t["pnl_tmn"]) for t in trades if t["setup"] == setup]
        by_setup[setup] = {
            "trades": len(sp),
            "pnl_tmn": round(sum(sp)),
            "win_rate_pct": round(100 * sum(p > 0 for p in sp) / len(sp), 1),
        }
    acks = [float(o["ack_ms"]) for o in orders if "ack_ms" in o]
    errors = [o for o in orders if "error" in o or "loop_error" in o]
    exits = Counter(t["exit"] for t in trades)
    sources = Counter((d.get("model") or {}).get("source") for d in cands)
    postures = j.read("postures.jsonl")
    state = j.load_state() or {}
    return {
        "mode": mode,
        "run": run_dir.name,
        "period": {
            "start": eq_rows[0]["ts"] if eq_rows else None,
            "end": eq_rows[-1]["ts"] if eq_rows else None,
            "bars": len(eq_rows),
        },
        "start_equity_tmn": round(start),
        "end_equity_tmn": round(end),
        "return_pct": round((end / start - 1) * 100, 3) if start else 0.0,
        "realized_pnl_tmn": round(sum(pnl)),
        "max_drawdown_pct": round(max_dd, 3),
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
        "avg_win_tmn": round(statistics.mean(wins)) if wins else None,
        "avg_loss_tmn": round(statistics.mean(losses)) if losses else None,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "volume_tmn": round(volume),
        "avg_trade_volume_tmn": round(volume / len(trades)) if trades else None,
        "trades_per_day": dict(sorted(per_day.items())),
        "exits": dict(exits),
        "by_setup": by_setup,
        "ai": {
            "candidates": len(cands),
            "taken": len(taken),
            "skipped_by_model": len(skip_model),
            "skipped_by_posture": len(skip_posture),
            "model_sources": {str(k): v for k, v in sources.items()},
            "postures": len(postures),
            "posture_sources": dict(Counter(p.get("source", "?").split(":")[0] for p in postures)),
        },
        "speed": {
            "order_ack_ms_p50": _pct(acks, 0.5),
            "order_ack_ms_p95": _pct(acks, 0.95),
            "bar_decision_latency_ms_p50": _pct([float(b["latency_ms"]) for b in bars], 0.5),
            "bar_compute_ms_p50": _pct([float(b["compute_ms"]) for b in bars], 0.5),
        },
        "stability": {"errors": len(errors), "orders": len([o for o in orders if "order_id" in o])},
        "open_positions_at_end": len(state.get("positions", {})),
        "killed": (state.get("guard") or {}).get("killed", False),
    }


def report_markdown(r: dict[str, Any]) -> str:
    lines = [
        f"# Zirak agent report — {r['mode']} `{r['run']}`",
        "",
        f"Period: {r['period']['start']} → {r['period']['end']} ({r['period']['bars']} bars)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Return (net, Toman) | {r['return_pct']:+.3f} % |",
        f"| Start → end equity | {r['start_equity_tmn']:,} → {r['end_equity_tmn']:,} TMN |",
        f"| Realised P&L | {r['realized_pnl_tmn']:,} TMN |",
        f"| Max drawdown | {r['max_drawdown_pct']:.3f} % |",
        f"| Trades (round trips) | {r['trades']} |",
        f"| Win rate | {r['win_rate_pct']} % |",
        f"| Profit factor | {r['profit_factor']} |",
        f"| Trading volume | {r['volume_tmn']:,} TMN |",
        f"| Average trade volume | {r['avg_trade_volume_tmn']} TMN |",
        f"| Trades per day | {r['trades_per_day']} |",
        f"| Exits | {r['exits']} |",
        f"| AI: candidates / taken / skipped by model / by posture | {r['ai']['candidates']} / {r['ai']['taken']} / "
        f"{r['ai']['skipped_by_model']} / {r['ai']['skipped_by_posture']} |",
        f"| Posture sources | {r['ai']['posture_sources']} |",
        f"| Order ack latency p50 / p95 | {r['speed']['order_ack_ms_p50']} / {r['speed']['order_ack_ms_p95']} ms |",
        f"| Bar close → decision p50 | {r['speed']['bar_decision_latency_ms_p50']} ms |",
        f"| Errors / orders | {r['stability']['errors']} / {r['stability']['orders']} |",
        f"| Open positions at end | {r['open_positions_at_end']} |",
        "",
        "By setup:",
        "",
        "| Setup | Trades | P&L (TMN) | Win rate |",
        "|---|---:|---:|---:|",
        *[
            f"| {k} | {v['trades']} | {v['pnl_tmn']:,} | {v['win_rate_pct']} % |"
            for k, v in r["by_setup"].items()
        ],
    ]
    return "\n".join(lines) + "\n"
