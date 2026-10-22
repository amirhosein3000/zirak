"""ML meta-labeler: the AI that decides, for every candidate, *whether* to trade it and *how big*.

Meta-labeling (López de Prado): explainable setups propose a side; a classifier trained on their
triple-barrier outcomes predicts the probability that *this* candidate reaches its take-profit before its
stop, after costs. The decision is economic, not a fixed threshold on an indicator:

    EV%  = p * (tp% - cost%) - (1 - p) * (sl% + cost%)
    take  if EV% >= min_ev_pct and p >= min_prob
    size  = fractional Kelly: f = p - (1 - p) / b,  b = (tp - cost) / (sl + cost);  multiplier = clip(f / kelly_ref, 0, 1)

Training is deterministic (fixed seeds, time-ordered data) so a judge can retrain and get the same model
(same data -> same `model_id`). Validation is out-of-time: fit on the first 70 %, measure on the last 30 %,
then refit on everything. With too little data the model falls back to each setup's smoothed historical
win rate, and the decision record says so.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from zirak.agent.features import FEATURES
from zirak.agent.setups import SETUPS

SEED = 7
PRIOR_WIN = 0.45  # pessimistic prior win rate for the fallback
PRIOR_WEIGHT = 20  # pseudo-observations behind the prior


def design_matrix(rows: pd.DataFrame) -> pd.DataFrame:
    """Model inputs: features + the candidate's own exits + one-hot setup."""
    X = rows.reindex(columns=[*FEATURES, "tp_pct", "sl_pct"]).astype(float).copy()
    for s in SETUPS:
        X[f"setup_{s}"] = (rows["setup"] == s).astype(float)
    return X


@dataclass
class ModelCard:
    """What the judges (and the decision log) need to know about the model in use."""

    model_id: str
    kind: str  # "gbm" | "logit" | "prior"
    trained_rows: int
    first_ts: str | None
    last_ts: str | None
    base_rate: float
    holdout_auc: float | None = None
    holdout_rows: int = 0
    holdout_taken: int = 0
    holdout_ev_all_pct: float | None = None  # mean net return of every holdout candidate
    holdout_ev_taken_pct: float | None = None  # mean net return of the candidates the model would take
    setup_win_rates: dict[str, float] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Verdict:
    prob: float
    ev_pct: float
    kelly: float
    size_mult: float
    take: bool
    source: str  # model kind that produced `prob`
    why: str


class MetaModel:
    def __init__(
        self,
        min_prob: float = 0.5,
        min_ev_pct: float = 0.05,
        kelly_ref: float = 0.25,
        min_rows: int = 120,
    ) -> None:
        self.min_prob = min_prob
        self.min_ev_pct = min_ev_pct
        self.kelly_ref = kelly_ref
        self.min_rows = min_rows
        self.pipe: Pipeline | None = None
        self.card = ModelCard("untrained", "prior", 0, None, None, PRIOR_WIN, setup_win_rates={})

    # ---- training ------------------------------------------------------------------------------
    def _make(self, n: int) -> Pipeline:
        if n >= 600:
            clf: Any = HistGradientBoostingClassifier(
                max_depth=3,
                max_iter=150,
                learning_rate=0.05,
                l2_regularization=1.0,
                min_samples_leaf=25,
                random_state=SEED,
            )
            return Pipeline([("clf", clf)])
        return Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("clf", LogisticRegression(C=0.3, max_iter=500, random_state=SEED)),
            ]
        )

    def fit(self, rows: pd.DataFrame, cost_pct: float) -> ModelCard:
        rows = rows.sort_values("ts", kind="stable").reset_index(drop=True)
        n = len(rows)
        win_rates = _setup_win_rates(rows)
        data_hash = hashlib.sha256(
            pd.util.hash_pandas_object(rows[["ts", "symbol", "setup", "label"]], index=False)
            .to_numpy()
            .tobytes()
        ).hexdigest()
        first = str(rows["ts"].iloc[0]) if n else None
        last = str(rows["ts"].iloc[-1]) if n else None
        base = float(rows["label"].mean()) if n else PRIOR_WIN
        if n < self.min_rows or rows["label"].nunique() < 2:
            self.pipe = None
            self.card = ModelCard(
                f"prior-{data_hash[:10]}",
                "prior",
                n,
                first,
                last,
                base,
                setup_win_rates=win_rates,
                notes=f"fewer than {self.min_rows} labelled candidates (or one class): smoothed setup win rates",
            )
            return self.card
        X, y = design_matrix(rows), rows["label"].to_numpy()
        cut = int(n * 0.7)
        auc = ev_all = ev_taken = None
        taken = 0
        if cut >= 60 and len(set(y[:cut])) == 2 and len(set(y[cut:])) == 2:
            pipe = self._make(cut).fit(X.iloc[:cut], y[:cut])
            p = pipe.predict_proba(X.iloc[cut:])[:, 1]
            auc = float(roc_auc_score(y[cut:], p))
            hold = rows.iloc[cut:]
            mask = np.array(
                [
                    self._ev(pp, tp, sl, cost_pct)[0] >= self.min_ev_pct and pp >= self.min_prob
                    for pp, tp, sl in zip(p, hold["tp_pct"], hold["sl_pct"], strict=True)
                ]
            )
            taken = int(mask.sum())
            ev_all = float(hold["net_ret_pct"].mean())
            ev_taken = float(hold["net_ret_pct"][mask].mean()) if taken else None
        self.pipe = self._make(n).fit(X, y)
        kind = "gbm" if n >= 600 else "logit"
        self.card = ModelCard(
            f"{kind}-{data_hash[:10]}",
            kind,
            n,
            first,
            last,
            base,
            auc,
            n - cut,
            taken,
            _r(ev_all),
            _r(ev_taken),
            win_rates,
        )
        return self.card

    # ---- deciding --------------------------------------------------------------------------------
    @staticmethod
    def _ev(p: float, tp: float, sl: float, cost: float) -> tuple[float, float]:
        win, loss = tp - cost, sl + cost
        ev = p * win - (1 - p) * loss
        kelly = p - (1 - p) / (win / loss) if win > 0 else -1.0
        return ev, kelly

    def prob(self, features: dict[str, float], setup: str, tp_pct: float, sl_pct: float) -> tuple[float, str]:
        if self.pipe is None:
            return self.card.setup_win_rates.get(setup, PRIOR_WIN), "prior"
        row = pd.DataFrame([{**features, "setup": setup, "tp_pct": tp_pct, "sl_pct": sl_pct}])
        return float(self.pipe.predict_proba(design_matrix(row))[0, 1]), self.card.kind

    def decide(
        self, features: dict[str, float], setup: str, tp_pct: float, sl_pct: float, cost_pct: float
    ) -> Verdict:
        p, source = self.prob(features, setup, tp_pct, sl_pct)
        ev, kelly = self._ev(p, tp_pct, sl_pct, cost_pct)
        size = float(np.clip(kelly / self.kelly_ref, 0.0, 1.0)) if kelly > 0 else 0.0
        take = ev >= self.min_ev_pct and p >= self.min_prob and size > 0
        if take:
            why = f"p={p:.2f}, EV={ev:+.2f}% >= {self.min_ev_pct}%, kelly={kelly:.2f}"
        elif p < self.min_prob:
            why = f"p={p:.2f} < {self.min_prob}"
        else:
            why = f"EV={ev:+.2f}% < {self.min_ev_pct}% (p={p:.2f})"
        return Verdict(round(p, 4), round(ev, 4), round(kelly, 4), round(size, 4), take, source, why)

    # ---- persistence -----------------------------------------------------------------------------
    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipe, directory / "model.joblib")
        params = {
            "min_prob": self.min_prob,
            "min_ev_pct": self.min_ev_pct,
            "kelly_ref": self.kelly_ref,
            "min_rows": self.min_rows,
        }
        card = {**self.card.to_dict(), "params": params}
        (directory / "model_card.json").write_text(json.dumps(card, indent=1, default=str), encoding="utf-8")
        return directory

    @classmethod
    def load(cls, directory: Path) -> MetaModel:
        card = json.loads((directory / "model_card.json").read_text(encoding="utf-8"))
        m = cls(**card.pop("params"))
        m.pipe = joblib.load(directory / "model.joblib")
        m.card = ModelCard(**card)
        return m


def _setup_win_rates(rows: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in SETUPS:
        sub = rows[rows["setup"] == s] if len(rows) else rows
        wins, n = (float(sub["label"].sum()), len(sub)) if len(sub) else (0.0, 0)
        out[s] = round((wins + PRIOR_WIN * PRIOR_WEIGHT) / (n + PRIOR_WEIGHT), 4)
    return out


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)
