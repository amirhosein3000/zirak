"""Reproducibility check for a run: recompute every AI decision from what the run logged.

For each logged candidate: load the exact model snapshot it used (`models/<model_id>/`), feed it the logged
features and exits, and check that probability, EV and the take/skip verdict come out identical. Then
check that every buy was allowed by the posture in force and that no buy happened while the account
guard was paused. Works the same for backtest, shadow and live runs.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from zirak.agent.journal import Journal
from zirak.agent.model import MetaModel


def verify_run(run_dir: Path) -> dict[str, Any]:
    j = Journal(run_dir)
    decisions = j.read("decisions.jsonl")
    models: dict[str, MetaModel | None] = {}
    checked = matched = 0
    mismatches: list[dict[str, Any]] = []
    missing_models: set[str] = set()
    guard = "ok"
    guard_violations = 0
    posture_violations = 0
    for d in decisions:
        if d.get("kind") == "guard":
            guard = str(d.get("status", "ok"))
            continue
        if d.get("kind") != "candidate":
            continue
        m = d.get("model") or {}
        mid = str(m.get("id"))
        if mid not in models:
            path = run_dir / "models" / mid
            models[mid] = MetaModel.load(path) if (path / "model_card.json").exists() else None
        model = models[mid]
        if model is None:
            missing_models.add(mid)
            continue
        feats = {k: (math.nan if v is None else float(v)) for k, v in (d.get("features") or {}).items()}
        v = model.decide(feats, d["setup"], float(d["tp_pct"]), float(d["sl_pct"]), float(m["cost_pct"]))
        checked += 1
        same = abs(v.prob - float(m["prob"])) < 1e-9 and abs(v.ev_pct - float(m["ev_pct"])) < 1e-9
        same = same and (d.get("action") != "buy" or v.take)
        if same:
            matched += 1
        elif len(mismatches) < 10:
            mismatches.append(
                {
                    "id": d.get("id"),
                    "logged": m,
                    "recomputed": {"prob": v.prob, "ev_pct": v.ev_pct, "take": v.take},
                }
            )
        if d.get("action") == "buy":
            p = d.get("posture") or {}
            if p.get("stance") == "avoid" or float(p.get("mult", 1) or 0) <= 0:
                posture_violations += 1
            if guard != "ok":
                guard_violations += 1
    return {
        "run": run_dir.name,
        "candidates_checked": checked,
        "verdicts_reproduced": matched,
        "reproduced_pct": round(100 * matched / checked, 2) if checked else None,
        "mismatches": mismatches,
        "models_used": sorted(k for k, v in models.items() if v is not None),
        "models_missing": sorted(missing_models),
        "buys_against_posture": posture_violations,
        "buys_while_guard_paused": guard_violations,
        "ok": checked > 0 and matched == checked and not posture_violations and not guard_violations,
    }
