# Wallex API — organized map

The user saved the Wallex developer docs as 46 text files. They were reorganized on 2026-10-22:
originals were renamed into `raw/` by topic, and 7 redundant files were deleted (see bottom). The
markdown files here are an English digest written for building Zirak. **They describe only what the
docs say, plus facts verified against the live API on 2026-10-22** (marked `VERIFIED-LIVE`).
Anything else is `UNVERIFIED`.

| File | What it covers | Used by Zirak? |
|---|---|---|
| [basics.md](basics.md) | Base URL, API key, auth header, data types, rate limits | Yes |
| [market-data.md](market-data.md) | Markets, candles (`udf/history`), depth, trades, fair price | Yes (public) |
| [spot-trading.md](spot-trading.md) | Order types, place / cancel / get / list / open orders | Yes (live mode only) |
| [account.md](account.md) | Balances, fee tier | Yes (live mode only) |
| [websocket.md](websocket.md) | Centrifugo v2 + deprecated v1, channels, limits, private events | Optional stream |
| [out-of-scope.md](out-of-scope.md) | Margin, trading credit, OTC, banking, **withdrawals** | **Never** |

## Raw source files (`raw/`)

| Topic | Raw files |
|---|---|
| Basics | `basics/intro.txt`, `basics/api-key.txt`, `basics/nav-and-main-wallet-balances.txt` (site nav + main-wallet balances body) |
| Market data | `market-data/{markets,candles,depth,trades}.txt` (guide pages) and `*.swagger-page.txt` (service pages: base URL, params) |
| Account | `account/fee.txt`, `account/fee.swagger-page.txt`, `account/balances.swagger-page.txt` |
| Spot | `spot/{what-is-spot,order-types,place-order,cancel-order,order-details,list-orders,open-orders}.txt` |
| WebSocket | `websocket/websocket.txt` (all channel pages, v1 + v2) |
| Out of scope | `out-of-scope/{banking-and-withdrawal,margin,trading-credit,otc}/` |

## Facts verified against the live API (2026-10-22, from this machine)

- `https://api.wallex.ir` answers. `api.wallex.com`, which the service pages show, **does not resolve** from here.
- The machine's HTTPS proxy (`127.0.0.1:10808`) breaks the TLS handshake to Wallex, so calls must go
  **direct** (`trust_env=False` in httpx, `proxy=None` in websockets).
- Public market data (`/hector/web/v1/markets`, `/v1/depth`, `/v1/trades`, `/v1/udf/history`,
  `/v1/all-fairPrice`) works **without** `x-api-key`.
- `/v1/trades` returns `x-ratelimit-limit: 600` and `x-ratelimit-remaining` headers (window not documented).
- Candle resolutions behave differently from the docs; see [market-data.md](market-data.md#candles).
- WebSocket v1 (`wss://api.wallex.ir/ws`) works. The v2 handshake (`/connection/websocket`) often returns
  **HTTP 503** when reconnecting quickly (it looks like connection rate limiting). One connect worked
  and answered `connect` with Centrifugo `6.9.1 OSS`.

## Conflicts between pages (and how Zirak resolves them)

| Topic | Page A | Page B | Zirak uses |
|---|---|---|---|
| Base URL | intro: `https://api.wallex.ir` is the only domain | service pages: `https://api.wallex.com` | `api.wallex.ir` (VERIFIED-LIVE) |
| Candle resolutions | guide: `1, 15, 60, 240, 480, 720, 1D, 2D, 3D` | service page: `1, 5, 15, 60, D` | native `1`, `60`, `1D` only, then aggregate 15m/4h locally (VERIFIED-LIVE) |
| `symbol` on `/v1/trades` | guide: optional | service page: required | always send it (without it: HTTP 422, VERIFIED-LIVE) |
| `x-api-key` on public data | service pages show it on every call | WebSocket: public needs no auth | send the key if set, else none (VERIFIED-LIVE: not required) |
| Place-order stop field | `stop_Price` (guide table) | — | never send it (Zirak uses only LIMIT / MARKET) |

## What is missing from the saved docs

1. **Spot swagger / spot "service docs" pages.** The nav lists *Get all markets depth*, *List active
   orders*, *Submit a new trading order*, *Cancel an existing order*, *Get order details*, *Cancel an
   order by path parameter*, but those pages weren't saved. Exact status enums, error codes and
   response casing are therefore `UNVERIFIED`.
2. **Base-services swagger file.** Only "download" links were saved.
3. **`GET /v1/all-fairPrice`** is referenced by the WebSocket page but has no page of its own (it works live).
4. **Minimum order size / min notional for spot markets.** The markets endpoint gives only
   `amount_precision` / `price_precision` (decimal places). OTC markets have `minQty`/`minNotional`, spot
   doesn't. Zirak keeps conservative placeholder minimums (`UNVERIFIED`).
5. **Fee tiers.** Only `GET /v1/account/fee` (needs an API key). There's no public fee table.
6. **REST rate limits** apart from order placement (20 per 10 s). The 600 limit header was seen live; its window is unknown.
7. **History limits for `udf/history`.** Not documented. Measured live (see market-data.md).
8. **Private WebSocket with an API key.** The private channel needs a JWT from `POST /v3/auth/token/refresh`,
   which uses the **logged-in browser cookie**, not the API key. A bot can't use it in practice, so
   Zirak polls order status over REST.
9. **Order status values.** Docs show `NEW`, `FILLED`, `CANCELED` as examples. A full list (partial fill,
   rejected, expired?) is missing.

## Deleted as redundant (2026-10-22)

| Deleted | Why |
|---|---|
| `10.txt` | Same "Get all markets" service page as `Spot8.txt` (kept as `market-data/markets.swagger-page.txt`) |
| `market.txt` | Subset of `spot markets.txt` (kept as `market-data/markets.txt`, which also defines the precision fields) |
| `کیف پول.txt` | Identical to `New Text Document (3).txt` (kept as `out-of-scope/banking-and-withdrawal/crypto-deposit-address.swagger-page.txt`) |
| `مستندات.txt` | Rendered pages of `Credit swagger.txt`, with the same 16 endpoints (kept as `trading-credit.openapi.yaml`) |
| `List margins.txt` | Rendered pages of `swagger (2).txt`, all 13 paths covered (kept as `margin.swagger.json`) |
| `swagger.txt`, `other.txt` | Merged into `out-of-scope/margin/margin-guide.txt` (intro paragraph + guide) |
