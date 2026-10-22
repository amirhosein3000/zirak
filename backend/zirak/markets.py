"""Fallback market metadata.

UNVERIFIED: these precisions and minimums are placeholders. When `WallexClient.get_markets()` is
implemented from docs/wallex-api, the real values replace these (`Market.verified=True`).
"""

from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path
from typing import Any

from zirak.models import ZERO, Market

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


# Placeholder spot minimum order value per quote currency. UNVERIFIED: the Wallex docs give no spot minimums.
MIN_NOTIONAL_FALLBACK = {"TMN": D("100000"), "USDT": D("5")}


def market_from_wallex(row: dict[str, Any]) -> Market:
    """Build a Market from one `/hector/web/v1/markets` row (precision = number of decimal places)."""
    quote = row["quote_asset"]
    qty_step = D(1).scaleb(-int(row["amount_precision"]))
    fallback = DEFAULT_MARKETS.get(row["symbol"])
    return Market(
        symbol=row["symbol"],
        base=row["base_asset"],
        quote=quote,
        price_step=D(1).scaleb(-int(row["price_precision"])),
        qty_step=qty_step,
        min_qty=qty_step,
        min_notional=fallback.min_notional if fallback else MIN_NOTIONAL_FALLBACK.get(quote, ZERO),
        verified=True,  # precision from the API; min_notional is still a placeholder
    )


def load_markets_file(path: Path) -> dict[str, Market]:
    """Read a markets.json snapshot written by the recorder (`zirak backfill` / `zirak record`)."""
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8")).get("markets", [])
    return {m.symbol: m for m in (market_from_wallex(r) for r in rows)}
