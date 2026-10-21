"""Runtime settings, read once from the environment (and an optional .env file).

Every variable here is documented in `.env.example` at the repo root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA_DIR = BACKEND_ROOT / "tests" / "fixtures" / "sample"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _dec(name: str, default: str | None) -> Decimal | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return Decimal(default) if default is not None else None
    return Decimal(raw.strip())


def _str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw.strip() if raw is not None and raw.strip() != "" else default


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _str(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    # --- trading mode & hard safety limits -------------------------------------------------
    live_trading: bool = False
    max_order_tmn: Decimal | None = None  # hard per-order cap for TMN-quoted markets (live only)
    max_order_usdt: Decimal | None = None  # hard per-order cap for USDT-quoted markets (live only)
    daily_loss_limit_pct: Decimal | None = Decimal("3")
    kill_file: Path = REPO_ROOT / "data" / "KILL"

    # --- exchange ---------------------------------------------------------------------------
    wallex_api_key: str | None = None
    wallex_base_url: str | None = None  # UNVERIFIED: no docs/wallex-api yet, so no default
    data_source: str = "replay"  # "replay" (offline) or "wallex" (live public data)
    markets: list[str] = field(default_factory=lambda: ["USDTTMN", "BTCTMN", "BTCUSDT", "ETHTMN", "ETHUSDT"])

    # --- paper trading simulation -------------------------------------------------------------
    fee_taker_pct: Decimal = Decimal("0.25")  # UNVERIFIED placeholder: set from your Wallex fee tier
    fee_maker_pct: Decimal = Decimal("0.20")  # UNVERIFIED placeholder
    slippage_bps: Decimal = Decimal("5")
    paper_start_tmn: Decimal = Decimal("100000000")
    paper_start_usdt: Decimal = Decimal("1000")
    fill_participation: Decimal = Decimal("0.10")  # max share of a candle's volume one order may take

    # --- storage ------------------------------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    db_path: Path = REPO_ROOT / "data" / "zirak.sqlite"
    replay_dir: Path = SAMPLE_DATA_DIR

    # --- LLM ----------------------------------------------------------------------------------
    mock_llm: bool = True
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_s: float = 30.0

    # --- API ----------------------------------------------------------------------------------
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])

    @property
    def fee_taker(self) -> Decimal:
        return self.fee_taker_pct / Decimal(100)

    @property
    def fee_maker(self) -> Decimal:
        return self.fee_maker_pct / Decimal(100)

    def max_order_for_quote(self, quote: str) -> Decimal | None:
        return {"TMN": self.max_order_tmn, "USDT": self.max_order_usdt}.get(quote)


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Build Settings from the process environment. `.env` at the repo root is loaded if present."""
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    data_dir = Path(_str("DATA_DIR", str(REPO_ROOT / "data")))
    return Settings(
        live_trading=_bool("LIVE_TRADING", False),
        max_order_tmn=_dec("MAX_ORDER_TMN", None),
        max_order_usdt=_dec("MAX_ORDER_USDT", None),
        daily_loss_limit_pct=_dec("DAILY_LOSS_LIMIT_PCT", "3"),
        kill_file=Path(_str("KILL_FILE", str(data_dir / "KILL"))),
        wallex_api_key=os.getenv("WALLEX_API_KEY") or None,
        wallex_base_url=os.getenv("WALLEX_BASE_URL") or None,
        data_source=_str("DATA_SOURCE", "replay"),
        markets=_list("MARKETS", "USDTTMN,BTCTMN,BTCUSDT,ETHTMN,ETHUSDT"),
        fee_taker_pct=_dec("FEE_TAKER_PCT", "0.25") or Decimal("0.25"),
        fee_maker_pct=_dec("FEE_MAKER_PCT", "0.20") or Decimal("0.20"),
        slippage_bps=_dec("SLIPPAGE_BPS", "5") or Decimal("5"),
        paper_start_tmn=_dec("PAPER_START_TMN", "100000000") or Decimal("100000000"),
        paper_start_usdt=_dec("PAPER_START_USDT", "1000") or Decimal("1000"),
        fill_participation=_dec("FILL_PARTICIPATION", "0.10") or Decimal("0.10"),
        data_dir=data_dir,
        db_path=Path(_str("DB_PATH", str(data_dir / "zirak.sqlite"))),
        replay_dir=Path(_str("REPLAY_DIR", str(SAMPLE_DATA_DIR))),
        mock_llm=_bool("MOCK_LLM", True),
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_model=os.getenv("LLM_MODEL") or None,
        llm_timeout_s=float(_str("LLM_TIMEOUT_S", "30")),
        cors_origins=_list("CORS_ORIGINS", "http://localhost:3000"),
    )
