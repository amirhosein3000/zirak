"""Run journal: everything a judge needs to audit a run, and everything a restart needs to resume.

`<runs>/<run_id>/`
  decisions.jsonl  one record per decision: every candidate (taken or skipped and why), every exit, every
                   guard change. The "decision log" the challenge asks for.
  postures.jsonl   every posture of the agent (LLM or rules), with its tool calls
  trades.jsonl     closed round trips (entry, exit, fees, P&L, reasons)
  orders.jsonl     every order we sent and its acknowledgement time (latency)
  equity.csv       equity over time (Toman)
  state.json       positions / pending orders / guard state, rewritten atomically after every change
  manifest.json    config, model card, code commit, mode, start time
"""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from zirak.config import REPO_ROOT


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return format(o, "f")
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "to_dict"):
        return o.to_dict()
    return str(o)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=_default)


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


class Journal:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self._seq = self._count("decisions.jsonl")

    def _count(self, name: str) -> int:
        path = self.dir / name
        if not path.exists():
            return 0
        with path.open(encoding="utf-8") as f:
            return sum(1 for _ in f)

    def _append(self, name: str, record: dict[str, Any]) -> None:
        with (self.dir / name).open("a", encoding="utf-8") as f:
            f.write(dumps(record) + "\n")

    def next_id(self) -> str:
        self._seq += 1
        return f"D{self._seq:06d}"

    def decision(self, record: dict[str, Any]) -> str:
        rid = record.get("id") or self.next_id()
        self._append("decisions.jsonl", {"id": rid, **record})
        return str(rid)

    def posture(self, record: dict[str, Any]) -> None:
        self._append("postures.jsonl", record)

    def bar(self, record: dict[str, Any]) -> None:
        self._append("bars.jsonl", record)

    def trade(self, record: dict[str, Any]) -> None:
        self._append("trades.jsonl", record)

    def order(self, record: dict[str, Any]) -> None:
        self._append("orders.jsonl", record)

    def equity(
        self, ts: datetime, equity: Decimal, cash: Decimal, exposure_pct: float, drawdown_pct: float
    ) -> None:
        path = self.dir / "equity.csv"
        new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "equity_tmn", "cash_tmn", "exposure_pct", "drawdown_pct"])
            w.writerow(
                [
                    ts.isoformat(),
                    format(equity.quantize(Decimal(1)), "f"),
                    format(cash.quantize(Decimal(1)), "f"),
                    f"{exposure_pct:.2f}",
                    f"{drawdown_pct:.3f}",
                ]
            )

    def save_state(self, state: dict[str, Any]) -> None:
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(dumps(state), encoding="utf-8")
        tmp.replace(self.dir / "state.json")

    def load_state(self) -> dict[str, Any] | None:
        path = self.dir / "state.json"
        if not path.exists():
            return None
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def manifest(self, data: dict[str, Any]) -> None:
        (self.dir / "manifest.json").write_text(
            json.dumps({**data, "commit": git_commit()}, ensure_ascii=False, indent=1, default=_default),
            encoding="utf-8",
        )

    def read(self, name: str) -> list[dict[str, Any]]:
        path = self.dir / name
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
