# Market data (public)

All of these worked **without an API key** on 2026-10-22 (VERIFIED-LIVE).

## Markets — `GET /hector/web/v1/markets`
Source: `raw/market-data/markets.txt`. Response: `result.markets[]`. 469 markets live.

| Field | Meaning |
|---|---|
| `symbol` | e.g. `BTCTMN` |
| `base_asset`, `quote_asset` | `BTC`, `TMN` |
| `fa_base_asset`, `fa_quote_asset`, `en_*` | display names |
| `price`, `change_24h`, `change_7D`, `volume_24h`, `quote_volume_24h` | stats (strings) |
| `amount_precision` | **decimal places of quantity** (BTC: 8, ETH: 5, USDT: 2) |
| `price_precision` | **decimal places of price** (TMN markets: 0, USDT markets: 2) |
| `is_spot` | tradable on spot. Only trade markets where this is `true` |
| `is_zero_fee`, `is_tmn_based`, `is_usdt_based`, `is_margin`, `is_otc`, `flags`, `categories`, `created_at` | misc |
| live-only extra fields | `fair_price`, `highest_24h_price`, `lowest_24h_price`, `is_market_type_enable`, `otc_min_notional`, `otc_max_notional`, `otc_buy_enabled`, `otc_sell_enabled` |

There's **no spot minimum order size / min notional** field. Zirak keeps placeholder minimums (UNVERIFIED).

## Candles — `GET /v1/udf/history`
Sources: `raw/market-data/candles.txt`, `candles.swagger-page.txt`, WebSocket candle page.

Query: `symbol`, `resolution`, `from`, `to` (Unix seconds).
Response (TradingView UDF): `{"s": "ok"|"no_data"|"error", "t": [..], "o": [..], "h": [..], "l": [..], "c": [..], "v": [..]}`.
`t` is the candle **start** time in seconds. o/h/l/c/v are decimal strings. Candles with no trades are
**missing**, not zero-filled.

### Resolution behaviour (VERIFIED-LIVE on BTCTMN, differs from the docs)
| `resolution` | Returns | Max bars per request | History reachable |
|---|---|---|---|
| `1` | 1-minute bars | ~1,440 (windows > ~1 day return `no_data`) | page by day |
| `5` | `{"s":"error","errmsg":"Invalid resolution!"}` | — | — |
| `15` | **1-minute bars**, not 15-minute | ~14k–27k | ~19 days |
| `60` | 1-hour bars | ~720 | paging backwards works (200+ days back) |
| `240`, `480`, `720` | **1-hour bars**, not 4/8/12-hour | ~1,440–2,135 | ~89 days per call |
| `1D` = `D` = `2D` = `3D` | 1-day bars | ~800 | since 2021 |
| `1h` | error | — | — |

When a window holds more bars than the cap, the server returns the **most recent** bars of the window
(ending at `to`). So **backfill pages backwards**: `to = earliest_t_received - 1`.

**Zirak:** uses only `1` → 1m, `60` → 1h and `1D` → 1d (matching the WebSocket table), and aggregates
15m from 1m and 4h from 1h locally.

## Depth — `GET /v1/depth?symbol=BTCTMN`
Sources: `raw/market-data/depth.txt`, `depth.swagger-page.txt`.
`result.ask[]` = sellers, `result.bid[]` = buyers. Each level: `{price, quantity, sum}`.
VERIFIED-LIVE: `price` and `quantity` arrive as **JSON numbers**, `sum` as a string. There are 50 levels per side;
asks ascending, bids descending. Zirak converts numbers through `str()` into `Decimal`. Missing
`symbol` → HTTP 400.

## Recent trades — `GET /v1/trades?symbol=BTCTMN`
Sources: `raw/market-data/trades.txt`, `trades.swagger-page.txt`.
`result.latestTrades[]` (50 live): `{symbol, quantity, price, sum, isBuyOrder, timestamp}`; decimal
strings, ISO timestamps, newest first.
`isBuyOrder` (WebSocket page): **true = the resting maker was a buy order**, so the taker *sold*.
Zirak maps `isBuyOrder=true` → aggressor side SELL.

## Fair price — `GET /v1/all-fairPrice`
Mentioned only on the WebSocket page (no page of its own). VERIFIED-LIVE: `result` = `{SYMBOL: number}`
for every market. Fair price = (best bid + best ask) / 2, rounded to 8 decimals.
