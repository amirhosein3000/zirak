"""The single choke point between Zirak and real money.

Rules (see CLAUDE.md "Non-negotiable safety rules"):
- Live orders require LIVE_TRADING=true AND a per-order size cap AND a daily loss limit AND the kill switch.
- When any condition fails, `require_live` raises *before* any network call is made.
- Withdrawal / transfer is never implemented anywhere.
"""

from __future__ import annotations

from decimal import Decimal

from zirak.config import Settings
from zirak.models import Market, OrderRequest


class LiveTradingDisabled(RuntimeError):
    """Raised when code tries to reach a real order endpoint without every live-trading condition."""


class HardLimitExceeded(RuntimeError):
    """Raised when a live order breaks the hard per-order cap from the environment."""


def live_blockers(settings: Settings, *, risk_reducing: bool = False) -> list[str]:
    """Every reason live trading is not allowed right now (empty list = allowed).

    `risk_reducing=True` is for cancels and read-only account calls (balances, fees, order status).
    They can't lose money, so they only need the API key: the kill switch must be able to cancel
    orders at any time, and the pre-flight check reads balances before live trading is switched on.
    """
    blockers: list[str] = []
    if risk_reducing:
        return [] if settings.wallex_api_key else ["WALLEX_API_KEY is not set"]
    if not settings.live_trading:
        blockers.append("LIVE_TRADING is not true")
    if not settings.max_order_tmn or settings.max_order_tmn <= 0:
        blockers.append("MAX_ORDER_TMN (per-order cap) is not set")
    if not settings.max_order_usdt or settings.max_order_usdt <= 0:
        blockers.append("MAX_ORDER_USDT (per-order cap) is not set")
    if not settings.daily_loss_limit_pct or settings.daily_loss_limit_pct <= 0:
        blockers.append("DAILY_LOSS_LIMIT_PCT is not set")
    if not risk_reducing and settings.kill_file.exists():
        blockers.append(f"kill switch is engaged ({settings.kill_file})")
    if not settings.wallex_api_key:
        blockers.append("WALLEX_API_KEY is not set")
    return blockers


def live_allowed(settings: Settings) -> bool:
    return not live_blockers(settings)


def require_live(settings: Settings, *, risk_reducing: bool = False) -> None:
    blockers = live_blockers(settings, risk_reducing=risk_reducing)
    if blockers:
        raise LiveTradingDisabled("; ".join(blockers))


def check_hard_limits(settings: Settings, market: Market, req: OrderRequest, ref_price: Decimal) -> None:
    """Hard per-order cap for real orders, independent of any strategy's own risk settings."""
    cap = settings.max_order_for_quote(market.quote)
    if cap is None:
        raise HardLimitExceeded(f"no per-order cap configured for quote {market.quote}")
    price = req.price if req.price is not None else ref_price
    notional = req.qty * price
    if notional > cap:
        raise HardLimitExceeded(f"order value {notional} {market.quote} exceeds cap {cap}")
