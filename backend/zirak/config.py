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
SAMPLE_DATA_DIR = BACKEND_ROOT / "tests" / "fixtures" / "sample"  # SYNTHETIC, for deterministic tests
WALLEX_SAMPLE_DIR = BACKEND_ROOT / "tests" / "fixtures" / "wallex"  # real data recorded from Wallex


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
    live_max_slippage_bps: Decimal = Decimal("50")  # protective price for live "market" orders
    live_order_ttl_s: float = 30.0  # cancel unfilled live orders after this many seconds
    kill_file: Path = REPO_ROOT / "data" / "KILL"

    # --- exchange ---------------------------------------------------------------------------
    wallex_api_key: str | None = None
    wallex_base_url: str = "https://api.wallex.ir"  # docs/wallex-api/basics.md (VERIFIED-LIVE)
    wallex_ws_url: str = "wss://api.wallex.ir/connection/websocket"  # Centrifugo v2
    wallex_ws_v1_url: str = "wss://api.wallex.ir/ws"  # deprecated v1, used as fallback
    wallex_use_system_proxy: bool = False  # the local HTTPS proxy breaks TLS to Wallex
    wallex_timeout_s: float = 20.0
    # Challenge / credit ("trading credit", prop) sub-account: own API key and wallet. Read-only prop calls.
    wallex_credit_account: bool = False  # balances from /v1/account/balances-detail (total/freeze/available)
    wallex_sub_account_client_id: str | None = None  # sent as `sub-account-client-id` on prop/balance calls
    wallex_prop_package_id: str | None = None  # to read the package's unavailableMarkets
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
    replay_dir: Path = WALLEX_SAMPLE_DIR

    # --- recorder -----------------------------------------------------------------------------
    recorder_resolutions: list[str] = field(default_factory=lambda: ["1m", "1h", "1d"])
    recorder_candle_interval_s: float = 60.0
    recorder_book_interval_s: float = 15.0
    recorder_trades_interval_s: float = 30.0
    live_poll_s: float = 5.0  # live paper runner: how often to poll the book / candles
    stale_data_s: float = 120.0  # no new buys when the newest closed candle is older than this (live)

    # --- LLM ----------------------------------------------------------------------------------
    mock_llm: bool = True
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_s: float = 30.0

    # --- optional modules (zirak/modules) -------------------------------------------------------
    modules: list[str] = field(
        default_factory=lambda: ["regime", "orderbook", "news", "portfolio", "alerts", "coach", "competition"]
    )
    news_source: str = "mock"  # "mock" (offline, canned) or "rss"
    news_rss_urls: list[str] = field(default_factory=list)
    news_risk: bool = False  # let very negative news shrink new buys of a running bot
    alerts_interval_s: float = 30.0
    alerts_telegram_token: str | None = None
    alerts_telegram_chat_id: str | None = None
    alerts_bale_token: str | None = None
    alerts_bale_chat_id: str | None = None

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
        live_max_slippage_bps=_dec("LIVE_MAX_SLIPPAGE_BPS", "50") or Decimal("50"),
        live_order_ttl_s=float(_str("LIVE_ORDER_TTL_S", "30")),
        kill_file=Path(_str("KILL_FILE", str(data_dir / "KILL"))),
        wallex_api_key=os.getenv("WALLEX_API_KEY") or None,
        wallex_base_url=_str("WALLEX_BASE_URL", "https://api.wallex.ir"),
        wallex_ws_url=_str("WALLEX_WS_URL", "wss://api.wallex.ir/connection/websocket"),
        wallex_ws_v1_url=_str("WALLEX_WS_V1_URL", "wss://api.wallex.ir/ws"),
        wallex_use_system_proxy=_bool("WALLEX_USE_SYSTEM_PROXY", False),
        wallex_timeout_s=float(_str("WALLEX_TIMEOUT_S", "20")),
        wallex_credit_account=_bool("WALLEX_CREDIT_ACCOUNT", False),
        wallex_sub_account_client_id=os.getenv("WALLEX_SUB_ACCOUNT_CLIENT_ID") or None,
        wallex_prop_package_id=os.getenv("WALLEX_PROP_PACKAGE_ID") or None,
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
        replay_dir=Path(_str("REPLAY_DIR", str(WALLEX_SAMPLE_DIR))),
        recorder_resolutions=_list("RECORDER_RESOLUTIONS", "1m,1h,1d"),
        recorder_candle_interval_s=float(_str("RECORDER_CANDLE_INTERVAL_S", "60")),
        recorder_book_interval_s=float(_str("RECORDER_BOOK_INTERVAL_S", "15")),
        recorder_trades_interval_s=float(_str("RECORDER_TRADES_INTERVAL_S", "30")),
        live_poll_s=float(_str("LIVE_POLL_S", "5")),
        stale_data_s=float(_str("STALE_DATA_S", "120")),
        mock_llm=_bool("MOCK_LLM", True),
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_model=os.getenv("LLM_MODEL") or None,
        llm_timeout_s=float(_str("LLM_TIMEOUT_S", "30")),
        modules=_list("MODULES", "regime,orderbook,news,portfolio,alerts,coach,competition"),
        news_source=_str("NEWS_SOURCE", "mock"),
        news_rss_urls=_list("NEWS_RSS_URLS", ""),
        news_risk=_bool("NEWS_RISK", False),
        alerts_interval_s=float(_str("ALERTS_INTERVAL_S", "30")),
        alerts_telegram_token=os.getenv("ALERTS_TELEGRAM_TOKEN") or None,
        alerts_telegram_chat_id=os.getenv("ALERTS_TELEGRAM_CHAT_ID") or None,
        alerts_bale_token=os.getenv("ALERTS_BALE_TOKEN") or None,
        alerts_bale_chat_id=os.getenv("ALERTS_BALE_CHAT_ID") or None,
        cors_origins=_list("CORS_ORIGINS", "http://localhost:3000"),
    )
