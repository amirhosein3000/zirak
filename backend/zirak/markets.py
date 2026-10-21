"""Fallback market metadata.

UNVERIFIED: these precisions and minimums are placeholders. When `WallexClient.get_markets()` is
implemented from docs/wallex-api, the real values replace these (`Market.verified=True`).
"""

from __future__ import annotations

from decimal import Decimal as D

from zirak.models import Market

DEFAULT_MARKETS: dict[str, Market] = {
    m.symbol: m
    for m in [
        Market(
            "USDTTMN",
            "USDT",
            "TMN",
            price_step=D("1"),
            qty_step=D("0.01"),
            min_qty=D("0.01"),
            min_notional=D("100000"),
        ),
        Market(
            "BTCTMN",
            "BTC",
            "TMN",
            price_step=D("1"),
            qty_step=D("0.000001"),
            min_qty=D("0.000001"),
            min_notional=D("100000"),
        ),
        Market(
            "ETHTMN",
            "ETH",
            "TMN",
            price_step=D("1"),
            qty_step=D("0.0001"),
            min_qty=D("0.0001"),
            min_notional=D("100000"),
        ),
        Market(
            "BTCUSDT",
            "BTC",
            "USDT",
            price_step=D("0.01"),
            qty_step=D("0.000001"),
            min_qty=D("0.000001"),
            min_notional=D("5"),
        ),
        Market(
            "ETHUSDT",
            "ETH",
            "USDT",
            price_step=D("0.01"),
            qty_step=D("0.0001"),
            min_qty=D("0.0001"),
            min_notional=D("5"),
        ),
    ]
}

# Persian display names for the UI and LLM prompts.
ASSET_NAMES_FA: dict[str, str] = {
    "BTC": "بیت‌کوین",
    "ETH": "اتریوم",
    "USDT": "تتر",
    "TMN": "تومان",
}


def market_name_fa(market: Market) -> str:
    base = ASSET_NAMES_FA.get(market.base, market.base)
    quote = ASSET_NAMES_FA.get(market.quote, market.quote)
    return f"{base}/{quote}"
