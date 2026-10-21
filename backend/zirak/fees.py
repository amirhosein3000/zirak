"""Fee and slippage maths, kept in one small module so it is easy to test and audit.

Fee convention (UNVERIFIED against Wallex docs): the fee is taken from the asset you *receive*.
A buy of `q` base pays `q * price` quote and receives `q * (1 - fee)` base.
A sell of `q` base gives `q` base and receives `q * price * (1 - fee)` quote.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from zirak.models import ONE, Market, Side

BPS = Decimal(10000)


@dataclass(frozen=True)
class FeeModel:
    maker: Decimal  # fraction, e.g. 0.002 for 0.2 %
    taker: Decimal

    def rate(self, is_maker: bool) -> Decimal:
        return self.maker if is_maker else self.taker


def apply_slippage(
    price: Decimal, side: Side, slippage_bps: Decimal, market: Market | None = None
) -> Decimal:
    """Move a reference price against us by `slippage_bps` and round to tick size (also against us)."""
    factor = slippage_bps / BPS
    raw = price * (ONE + factor) if side is Side.BUY else price * (ONE - factor)
    return market.round_price(raw, side) if market is not None else raw


@dataclass(frozen=True)
class FillAmounts:
    base_delta: Decimal  # change in base balance (+ for buy, - for sell)
    quote_delta: Decimal  # change in quote balance (- for buy, + for sell)
    fee: Decimal
    fee_asset: str


def fill_amounts(market: Market, side: Side, price: Decimal, qty: Decimal, fee_rate: Decimal) -> FillAmounts:
    """Balance changes for one fill under the fee convention above."""
    notional = price * qty
    if side is Side.BUY:
        fee = qty * fee_rate
        return FillAmounts(base_delta=qty - fee, quote_delta=-notional, fee=fee, fee_asset=market.base)
    fee = notional * fee_rate
    return FillAmounts(base_delta=-qty, quote_delta=notional - fee, fee=fee, fee_asset=market.quote)


def round_trip_cost_pct(fees: FeeModel, slippage_bps: Decimal) -> Decimal:
    """Approximate % cost of buying and selling once with market orders: 2 * (taker + slippage)."""
    return (2 * fees.taker + 2 * slippage_bps / BPS) * 100
