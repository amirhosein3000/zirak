"""Read-only HTTP view of the agent's runs for the `/agent` page (monitoring and the demo video).

Runs are read from `<DATA_DIR>/runs/`. Nothing here can trade or change a run.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from zirak.agent.config import AgentConfig
from zirak.agent.journal import Journal
from zirak.agent.report import build_report

router = APIRouter(prefix="/api/agent", tags=["agent"])

PRIORITY = {"live": 0, "shadow": 1, "backtest": 2}


def _runs(request: Request) -> Path:
    path: Path = request.app.state.zirak.settings.data_dir / "runs"
    return path


def _run(request: Request, name: str) -> Path:
    path = _runs(request) / Path(name).name
    if not (path / "manifest.json").exists():
        raise HTTPException(404, "اجرا پیدا نشد")
    return path


@router.get("/runs")
async def runs(request: Request) -> list[dict[str, Any]]:
    out = []
    for p in _runs(request).glob("*"):
        mf = p / "manifest.json"
        if not mf.exists():
            continue
        m = json.loads(mf.read_text(encoding="utf-8"))
        out.append(
            {
                "run": p.name,
                "mode": m.get("mode"),
                "start": m.get("start"),
                "commit": m.get("commit"),
                "updated": p.stat().st_mtime,
            }
        )
    out.sort(key=lambda r: (PRIORITY.get(str(r["mode"]), 9), -float(r["updated"])))
    return out


@router.get("/runs/{name}")
async def run_summary(name: str, request: Request, decisions: int = 60) -> dict[str, Any]:
    path = _run(request, name)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    cfg = AgentConfig.model_validate(manifest["config"])
    j = Journal(path)
    report = build_report(path, cfg, manifest["mode"])
    equity: list[dict[str, Any]] = []
    eq_path = path / "equity.csv"
    if eq_path.exists():
        with eq_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        step = max(1, len(rows) // 400)
        equity = [
            {"ts": r["ts"], "equity": float(r["equity_tmn"]), "drawdown": float(r["drawdown_pct"])}
            for r in rows[::step] + ([rows[-1]] if rows and (len(rows) - 1) % step else [])
        ]
    feed = [
        {k: v for k, v in d.items() if k != "features"}
        for d in j.read("decisions.jsonl")
        if d.get("kind") in ("candidate", "entry_filled", "exit", "guard", "kill", "reconcile")
    ][-max(1, min(decisions, 300)) :]
    postures = j.read("postures.jsonl")
    state = j.load_state() or {}
    return {
        "run": name,
        "mode": manifest["mode"],
        "commit": manifest.get("commit"),
        "config": {
            "markets": cfg.markets,
            "resolution": cfg.resolution,
            "setups": cfg.setups,
            "risk": cfg.risk.model_dump(),
            "clock": cfg.clock.model_dump(mode="json"),
        },
        "report": report,
        "equity": equity,
        "positions": list((state.get("positions") or {}).values()),
        "guard": state.get("guard"),
        "posture": postures[-1] if postures else None,
        "model": manifest.get("model"),
        "decisions": list(reversed(feed)),
    }


@router.get("/runs/{name}/decisions/{decision_id}")
async def decision(name: str, decision_id: str, request: Request) -> dict[str, Any]:
    rows = Journal(_run(request, name)).read("decisions.jsonl")
    main = next((d for d in rows if d.get("id") == decision_id), None)
    if main is None:
        raise HTTPException(404, "تصمیم پیدا نشد")
    return {"decision": main, "follow_ups": [d for d in rows if d.get("ref") == decision_id]}
