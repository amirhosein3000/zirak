# WebSocket

Source: `raw/websocket/websocket.txt`. Infrastructure: **Centrifugo**.

## Two versions
| | v1 (deprecated, still works) | v2 (Centrifugo, recommended) |
|---|---|---|
| URL | `wss://api.wallex.ir/ws` | `wss://api.wallex.ir/connection/websocket` (no trailing `/`, or 404) |
| First frame | server sends `{"sid", "upgrades", "pingInterval":20000, "pingTimeout":30000, "maxPayload"}` | client sends `{"id":1,"connect":{}}` |
| Subscribe | `["subscribe", {"channel": "BTCTMN@trade"}]` | `{"id":2,"subscribe":{"channel":"public:BTCTMN@trade"}}` → `{"id":2,"subscribe":{}}` |
| Message | `["BTCTMN@trade", {...}]` | `{"push":{"channel":"public:BTCTMN@trade","pub":{"data":{...}}}}` |
| Ping | standard WS ping/pong frames | server sends `{}`, client must reply `{}` within 8 s (else close 3012) |
| Unsubscribe | `["unsubscribe", {"channel": "..."}]` | Centrifugo unsubscribe |
| Limits | closes after **30 min**; max 50 subscribe commands per connection; >100 queued messages are dropped | max **64 channels** per connection (error 106) |
| VERIFIED-LIVE | works; buyDepth snapshots ~7/s and trades arrive | handshake often **HTTP 503** on quick reconnects; worked once (`version 6.9.1 OSS`) |

One frame may contain several JSON messages separated by `\n`.

## Public channels (v2 names; for v1 drop the `public:` / `orderbook:` prefix)
| Channel | Payload |
|---|---|
| `public:<SYMBOL>@trade` | `{isBuyOrder, quantity, price, timestamp}`. `isBuyOrder=true` means the **maker was the buy order** |
| `orderbook:<SYMBOL>@buyDepth` / `@sellDepth` | `[{price, quantity, sum}, ...]`: a **full snapshot of one side** each message (replace, don't merge); numbers, not strings |
| `public:all@price` | `{symbol, price, "24h_ch"}`, sent per market on change |
| `public:all@fairPrice` (v2 only) | `{ts, prices: {SYMBOL: "decimal"}}` every ~20 s (up to 35 s); ~46–50 KB |
| `candle:<SYMBOL>@1m|1h|1d` (v2 only) | UDF shape with one element per array; repeated messages with the same `t` replace the open candle; keeps the last 10 messages for 2 min (`history`) |

Nothing is replayed on subscribe (no initial snapshot), and messages missed during a disconnect are
lost, except candle channels (10 messages / 2 min). Recommended: load REST first, then stream.

## Private channel (not usable by a bot with an API key)
v2: `private:user#<userId>`. It's joined automatically from a JWT obtained via `POST /v3/auth/token/refresh`,
**authenticated by the logged-in user's cookie** (900 s TTL). v1: subscribe to the `stream_key` from the login
response. Events: `balanceUpdated`, `orderSaved`, `orderRemoved`, `tradeDetails` (has `feeAmount`,
`feeCurrency`, `isMaker`, `clientOrderID`).
→ Zirak tracks orders by **REST polling** instead (`GET /v1/account/orders/{clientOrderId}`).

## Errors (v2)
102 unknown channel · 103 permission denied · 105 already subscribed · 106 limit exceeded · 107 bad request ·
108 not available · 109 token expired. Close codes 3000–3499 are retryable; 3500+ are not.

## Zirak's use
`WallexClient.stream()` uses v2 with exponential backoff on 503 and falls back to v1 (both documented). The
recorder and the live paper runner use **REST polling** by default because it's the path verified to work here.
