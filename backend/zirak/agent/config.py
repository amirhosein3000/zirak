"""Agent configuration: one JSON file describes a run completely (markets, setups, model, risk, clock).

`backend/config/challenge.json` is the configuration used in the Wallex challenge. Re-running a backtest
or a replay with the same file, data and model gives the same decisions.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from zirak.agent.setups import SETUPS
from zirak.models import RESOLUTION_SECONDS


class RiskSettings(BaseModel):
    risk_per_trade_pct: float = Field(0.6, gt=0, le=3)  # equity lost if the stop is hit
    max_position_pct: float = Field(30, gt=0, le=100)  # one market's position, % of equity
    max_exposure_pct: float = Field(70, gt=0, le=100)  # all positions together
    max_positions: int = Field(3, ge=1, le=10)
    cash_buffer_pct: float = Field(1.0, ge=0, le=10)  # never spend the last % of cash (fees, rounding)
    daily_loss_pct: float = Field(2.5, gt=0, le=20)  # vs equity at the start of the UTC day -> no entries
    dd_pause_pct: float = Field(5, gt=0, le=50)  # drawdown from peak -> no entries
    dd_kill_pct: float = Field(8, gt=0, le=60)  # drawdown from peak -> flatten everything + kill switch
    # credit plan: keep this fraction of the cushion (start - liquidation limit) untouched
    liquidation_pause_cushion: float = Field(0.6, ge=0, le=1)  # below 60 % of the cushion left -> no entries
    liquidation_kill_cushion: float = Field(0.3, ge=0, le=1)  # below 30 % left -> flatten + kill
    cooldown_bars: int = Field(2, ge=0, le=100)  # no re-entry in a market right after a stop


class ModelSettings(BaseModel):
    min_prob: float = Field(0.5, ge=0, le=1)
    min_ev_pct: float = Field(0.05, ge=-1, le=5)
    kelly_ref: float = Field(0.25, gt=0, le=1)
    min_rows: int = Field(120, ge=10)
    retrain_hours: float = Field(24, gt=0)  # walk-forward retraining cadence (backtest and live)
    train_days: float = Field(90, gt=0)  # how much history each (re)training uses


class ExecutionSettings(BaseModel):
    entry: Literal["maker_first", "taker"] = "maker_first"
    maker_offset_bps: float = Field(5, ge=0, le=100)  # entry limit this far below the reference price
    maker_wait_s: float = Field(180, ge=5)  # live: cancel an unfilled maker entry after this long
    max_slippage_bps: float = Field(40, ge=1, le=300)  # marketable exits: worst acceptable price
    poll_s: float = Field(5, ge=1, le=120)  # live/shadow: book / order / stop checks


class ChallengeClock(BaseModel):
    start: datetime | None = None  # UTC
    end: datetime | None = None  # UTC; everything must be Toman again before this
    no_entry_before_end_h: float = Field(4, ge=0)
    flatten_before_end_min: float = Field(90, ge=0)  # start orderly exits (maker / near touch)
    hard_flatten_before_end_min: float = Field(30, ge=0)  # marketable exits, whatever the price


class AgentConfig(BaseModel):
    name: str = Field("challenge", pattern=r"^[A-Za-z0-9_-]+$")
    markets: list[str] = Field(default_factory=lambda: ["BTCTMN", "ETHTMN", "USDTTMN"])
    #: read for features (cross rates), never traded
    context_markets: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    resolution: str = "1h"
    setups: list[str] = Field(default_factory=lambda: ["mean_reversion", "breakout", "basis_reversion"])
    initial_equity_tmn: float = Field(5_000_000, gt=0)  # paper runs (backtest / shadow)
    posture_interval_min: float = Field(60, gt=0)
    risk: RiskSettings = Field(default_factory=lambda: RiskSettings.model_validate({}))
    model: ModelSettings = Field(default_factory=lambda: ModelSettings.model_validate({}))
    execution: ExecutionSettings = Field(default_factory=lambda: ExecutionSettings.model_validate({}))
    clock: ChallengeClock = Field(default_factory=lambda: ChallengeClock.model_validate({}))

    @field_validator("markets")
    @classmethod
    def _toman_only(cls, v: list[str]) -> list[str]:
        bad = [m for m in v if not m.endswith("TMN")]
        if bad:
            raise ValueError(f"only Toman markets can be traded (profit is realised in Toman): {bad}")
        return v

    @field_validator("resolution")
    @classmethod
    def _res(cls, v: str) -> str:
        if v not in RESOLUTION_SECONDS:
            raise ValueError(f"unknown resolution {v}")
        return v

    @field_validator("setups")
    @classmethod
    def _setups(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in SETUPS]
        if bad:
            raise ValueError(f"unknown setups {bad}; known: {list(SETUPS)}")
        return v

    @property
    def all_markets(self) -> list[str]:
        return list(dict.fromkeys([*self.markets, *self.context_markets]))

    @classmethod
    def load(cls, path: Path | None) -> AgentConfig:
        if path is None:
            return cls.model_validate({})
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
