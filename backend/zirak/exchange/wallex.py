"""Real Wallex client, built only from docs/wallex-api/ (see that folder's README for the map).

Public market data works without a key (VERIFIED-LIVE 2026-10-22); the key is still sent on every
call when `WALLEX_API_KEY` is set, as the docs show it on every request. Private (account / order)
methods call the live-trading guard *first*, so with LIVE_TRADING=false they raise
`LiveTradingDisabled` before any network I/O.

There is deliberately no withdrawal or transfer method, and there must never be one.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from zirak.config import Settings
from zirak.data.aggregate import DERIVED_FROM, aggregate
from zirak.exchange.base import ExchangeClient, MarketEvent
from zirak.exchange.guard import require_live
from zirak.markets import market_from_wallex
from zirak.models import (
    ZERO,
    Balance,
    BookLevel,
    Candle,
    Market,
    Order,
    OrderBook,
    OrderRequest,
    OrderStatus,
    OrderType,
    PublicTrade,
    Side,
    ensure_utc,
    resolution_delta,
    utcnow,
)

# Our resolution -> Wallex udf `resolution`, and how many seconds of history to ask for per request.
# Only these three behave as documented live; see docs/wallex-api/market-data.md#candles.
NATIVE_RESOLUTIONS: dict[str, tuple[str, int]] = {
    "1m": ("1", 20 * 3600),  # >~1 day windows return no_data
    "1h": ("60", 25 * 86400),  # cap ~720 bars per request
    "1d": ("1D", 700 * 86400),  # cap ~800 bars per request
}

# Wallex order status -> ours. Only NEW / FILLED / CANCELED appear in the docs; the rest is defensive.
STATUS_MAP = {
    "NEW": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "FINISHED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "CANCELLED": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.CANCELED,
}


class WallexAPIError(RuntimeError):
    def __init__(self, status: int, message: str, body: Any = None) -> None:
        super().__init__(f"Wallex HTTP {status}: {message}")
        self.status = status
        self.body = body


def D(value: Any) -> Decimal:
    """Decimal from a Wallex number or number-string (numbers go through str to stay exact)."""
    if value is None or value == "":
        return ZERO
    d = Decimal(str(value))
    # Strip Wallex's 16 trailing zeros without switching to exponent notation (value unchanged).
    return d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize()


def _ts(value: Any) -> datetime:
    """ISO-8601 string, unix seconds or unix milliseconds -> aware UTC datetime."""
    if isinstance(value, int | float) or (isinstance(value, str) and value.isdigit()):
        n = float(value)
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, UTC)
    if isinstance(value, str) and value:
        return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    return utcnow()


class WallexClient(ExchangeClient):
    name = "wallex"
    is_real = True

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.wallex_base_url,
            timeout=settings.wallex_timeout_s,
            trust_env=settings.wallex_use_system_proxy,
            transport=transport,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        self._markets: dict[str, Market] = {}
        self.rate_limit_remaining: int | None = None
        self._balances_cache: tuple[float, dict[str, Balance]] | None = None

    async def close(self) -> None:
        await self._client.aclose()

    # ---- HTTP ----------------------------------------------------------------------------------
    async def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None
    ) -> Any:
        headers = {"x-api-key": self.settings.wallex_api_key} if self.settings.wallex_api_key else {}
        # Only idempotent reads are retried. A POST that times out is never re-sent blindly.
        attempts = 4 if method == "GET" else 1
        delay = 1.0
        for attempt in range(attempts):
            try:
                r = await self._client.request(method, path, params=params, json=body, headers=headers)
            except httpx.TransportError:
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
                continue
            remaining = r.headers.get("x-ratelimit-remaining")
            if remaining is not None and remaining.isdigit():
                self.rate_limit_remaining = int(remaining)
            if (r.status_code == 429 or r.status_code >= 500) and attempt < attempts - 1:
                retry_after = r.headers.get("retry-after")
                await asyncio.sleep(float(retry_after) if retry_after and retry_after.isdigit() else delay)
                delay *= 2
                continue
            try:
                data = r.json()
            except json.JSONDecodeError as e:
                raise WallexAPIError(r.status_code, r.text[:200]) from e
            if r.status_code >= 400 or (isinstance(data, dict) and data.get("success") is False):
                msg = data.get("message", "") if isinstance(data, dict) else str(data)
                raise WallexAPIError(r.status_code, str(msg)[:300], data)
            return data
        raise WallexAPIError(0, "unreachable")

    # ---- public market data ------------------------------------------------------------------
    async def get_markets(self) -> list[Market]:
        markets = [market_from_wallex(m) for m in await self.raw_markets() if m.get("is_spot")]
        self._markets = {m.symbol: m for m in markets}
        return markets

    async def raw_markets(self) -> list[dict[str, Any]]:
        """The unparsed market list (prices, 24h stats) for the UI and the recorder."""
        data = await self._request("GET", "/hector/web/v1/markets")
        markets: list[dict[str, Any]] = data["result"]["markets"]
        return markets

    async def _history(self, symbol: str, native: str, start: int, end: int) -> list[Candle]:
        data = await self._request(
            "GET", "/v1/udf/history", {"symbol": symbol, "resolution": native, "from": start, "to": end}
        )
        if not isinstance(data, dict) or data.get("s") != "ok":
            return []
        return [
            Candle(datetime.fromtimestamp(int(t), UTC), D(o), D(h), D(lo), D(c), D(v))
            for t, o, h, lo, c, v in zip(
                data["t"], data["o"], data["h"], data["l"], data["c"], data["v"], strict=False
            )
        ]

    async def get_candles(
        self, symbol: str, resolution: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Candle]:
        """Closed candles in [start, end), oldest first. 5m/15m/4h are aggregated from 1m/1h."""
        now = utcnow()
        end = min(end or now, now)
        start = start or end - timedelta(days=7)
        if resolution in DERIVED_FROM:
            base = await self.get_candles(symbol, DERIVED_FROM[resolution], start, end)
            return [c for c in aggregate(base, resolution, until=end) if c.ts >= start]
        if resolution not in NATIVE_RESOLUTIONS:
            raise ValueError(f"unsupported resolution {resolution}")
        native, window = NATIVE_RESOLUTIONS[resolution]
        step = resolution_delta(resolution)
        lo, hi = int(start.timestamp()), int(end.timestamp())
        found: dict[datetime, Candle] = {}
        cursor = hi
        while cursor > lo:
            win_start = max(lo, cursor - window)
            batch = await self._history(symbol, native, win_start, cursor)
            for c in batch:
                found[c.ts] = c
            if batch and batch[0].ts.timestamp() > win_start + step.total_seconds():
                cursor = int(batch[0].ts.timestamp()) - 1  # server capped the window: keep paging back
            else:
                cursor = win_start
        return [c for ts, c in sorted(found.items()) if ts >= start and ts + step <= end]

    async def get_order_book(self, symbol: str) -> OrderBook:
        data = await self._request("GET", "/v1/depth", {"symbol": symbol})
        res = data["result"]
        bids = [BookLevel(D(x["price"]), D(x["quantity"])) for x in res.get("bid", [])]
        asks = [BookLevel(D(x["price"]), D(x["quantity"])) for x in res.get("ask", [])]
        bids.sort(key=lambda lv: lv.price, reverse=True)
        asks.sort(key=lambda lv: lv.price)
        return OrderBook(symbol, utcnow(), bids, asks)

    async def get_recent_trades(self, symbol: str) -> list[PublicTrade]:
        data = await self._request("GET", "/v1/trades", {"symbol": symbol})
        out = []
        for t in data["result"].get("latestTrades", []):
            # isBuyOrder=true means the resting maker was a buy, so the aggressor sold.
            side = Side.SELL if t.get("isBuyOrder") else Side.BUY
            out.append(
                PublicTrade(
                    t.get("symbol", symbol), _ts(t["timestamp"]), D(t["price"]), D(t["quantity"]), side
                )
            )
        out.sort(key=lambda t: t.ts)
        return out

    async def get_fair_prices(self) -> dict[str, Decimal]:
        """`GET /v1/all-fairPrice`: referenced by the WebSocket docs, shape VERIFIED-LIVE."""
        data = await self._request("GET", "/v1/all-fairPrice")
        return {k: D(v) for k, v in data.get("result", {}).items()}

    # ---- live stream (WebSocket) -------------------------------------------------------------------
    async def stream(self, symbols: list[str]) -> AsyncIterator[MarketEvent]:
        """Trades and full-side depth snapshots. Centrifugo v2 first; falls back to the documented
        (deprecated) v1 endpoint when v2 keeps refusing the handshake (HTTP 503, seen live)."""
        from zirak.exchange.wallex_ws import stream_events

        async for event in stream_events(self.settings, symbols):
            yield event

    # ---- private: guarded --------------------------------------------------------------------
    async def get_balances(self) -> dict[str, Balance]:
        require_live(self.settings, risk_reducing=True)
        if self._balances_cache and time.monotonic() - self._balances_cache[0] < 3:
            return self._balances_cache[1]
        data = await self._request("GET", "/v1/account/balances")
        out: dict[str, Balance] = {}
        for asset, b in data["result"]["balances"].items():
            value, locked = D(b.get("value")), D(b.get("locked"))
            # UNVERIFIED: we read `value` as the total, so free = value - locked.
            out[asset] = Balance(asset, max(value - locked, ZERO), locked)
        self._balances_cache = (time.monotonic(), out)
        return out

    async def get_fees(self) -> dict[str, tuple[Decimal, Decimal]]:
        """symbol -> (maker rate, taker rate). Rates as returned (fraction vs percent UNVERIFIED)."""
        require_live(self.settings, risk_reducing=True)
        data = await self._request("GET", "/v1/account/fee")
        return {s: (D(v.get("makerFeeRate")), D(v.get("takerFeeRate"))) for s, v in data["result"].items()}

    async def place_order(self, req: OrderRequest) -> Order:
        require_live(self.settings)
        if req.type is not OrderType.LIMIT or req.price is None:
            # Live orders are always marketable LIMIT orders with a protective price (see Executor):
            # the docs require `price` on every order and a plain MARKET order has no slippage cap.
            raise ValueError("WallexClient only places LIMIT orders with a price")
        client_id = "zirak_" + secrets.token_hex(8)
        body = {
            "symbol": req.symbol,
            "side": req.side.value.upper(),
            "type": "LIMIT",
            "price": str(req.price),
            "quantity": str(req.qty),
            "client_id": client_id,
        }
        self._balances_cache = None
        data = await self._request("POST", "/v1/account/orders", body=body)
        return self._parse_order(data["result"], fallback_id=client_id, tag=req.client_tag)

    async def cancel_order(self, symbol: str, order_id: str) -> Order:
        # Cancelling reduces risk, so it works while the kill switch is engaged (but still needs live mode).
        require_live(self.settings, risk_reducing=True)
        self._balances_cache = None
        data = await self._request("DELETE", f"/v1/account/orders/{order_id}")
        return self._parse_order(data["result"], fallback_id=order_id)

    async def get_order(self, symbol: str, order_id: str) -> Order:
        require_live(self.settings, risk_reducing=True)
        data = await self._request("GET", f"/v1/account/orders/{order_id}")
        return self._parse_order(data["result"], fallback_id=order_id)

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        require_live(self.settings, risk_reducing=True)
        params = {"symbol": symbol, "per_page": 100} if symbol else {"per_page": 100}
        data = await self._request("GET", "/v1/account/openOrders", params)
        return [self._parse_order(o) for o in flatten_orders(data.get("result"))]

    # ---- parsing -------------------------------------------------------------------------------
    def _parse_order(self, o: dict[str, Any], fallback_id: str = "", tag: str = "") -> Order:
        fills = o.get("fills") or []
        executed = D(o.get("executedQty"))
        quote = D(o.get("executedSum")) or sum((D(f.get("sum")) for f in fills), ZERO)
        fee = D(o.get("fee")) or sum((D(f.get("fee")) for f in fills), ZERO)
        fee_asset = ""
        if fills:
            fa = fills[-1].get("feeAsset")
            fee_asset = fa if isinstance(fa, str) else ""
        raw_status = str(o.get("status") or "").upper()
        status = STATUS_MAP.get(raw_status)
        if status is None:  # unknown or missing status: infer from the `active` flag and fills
            orig = D(o.get("origQty"))
            if o.get("active"):
                status = OrderStatus.PARTIALLY_FILLED if executed > 0 else OrderStatus.NEW
            else:
                status = OrderStatus.FILLED if orig > 0 and executed >= orig else OrderStatus.CANCELED
        if status is OrderStatus.NEW and executed > 0:
            status = OrderStatus.PARTIALLY_FILLED
        side = Side.BUY if str(o.get("side", "")).upper() == "BUY" else Side.SELL
        otype = OrderType.MARKET if str(o.get("type", "")).upper() == "MARKET" else OrderType.LIMIT
        created = _ts(o.get("created_at")) if o.get("created_at") else utcnow()
        return Order(
            id=str(o.get("clientOrderId") or fallback_id),
            symbol=str(o.get("symbol", "")),
            side=side,
            type=otype,
            qty=D(o.get("origQty")),
            price=D(o.get("price")) if o.get("price") not in (None, "") else None,
            status=status,
            created_at=created,
            updated_at=_ts(o.get("updated_at")) if o.get("updated_at") else created,
            filled_qty=executed,
            quote_filled=quote,
            fee=fee,
            fee_asset=fee_asset,
            client_tag=tag,
        )


def flatten_orders(result: Any) -> list[dict[str, Any]]:
    """openOrders/orders `result` shape is UNVERIFIED (the doc example is a swagger map placeholder):
    accept a list, {"orders": [...]}, or a map of lists."""
    if result is None:
        return []
    if isinstance(result, list):
        return [o for o in result if isinstance(o, dict)]
    if isinstance(result, dict):
        if "clientOrderId" in result:
            return [result]
        out: list[dict[str, Any]] = []
        for v in result.values():
            out.extend(flatten_orders(v) if isinstance(v, list | dict) else [])
        return out
    return []
