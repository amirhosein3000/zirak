# Basics

Sources: `raw/basics/intro.txt`, `raw/basics/api-key.txt`, swagger pages.

## Base URL and transport
- REST: `https://api.wallex.ir` (intro: "all APIs are only available via the official domain https://api.wallex.ir").
  The service pages show `https://api.wallex.com`, which doesn't resolve from here (VERIFIED-LIVE).
- JSON responses. Requests that have a body: JSON with `Content-Type: application/json`.
- Envelope: `{"result": ..., "message": "...", "success": true}`; lists may add `result_info {page, per_page, count, total_count}`.
- Errors seen live: `{"message": "...", "success": false, "code": 400}` (and HTTP 422 on validation).

## Authentication
- Header `x-api-key: <key>` on private calls.
- Keys are created in the Wallex web panel. Permissions: **read** (default), **trade** (optional),
  **withdraw** (optional, IP-bound). **Zirak needs read + trade only; never enable withdraw.**
- Max 3 keys per account. Each key has an expiry date and is shown only once.
- Trading-credit (prop) sub-accounts have their own keys and also need a `sub-account-client-id` header.
  Zirak doesn't use sub-accounts.

## Data types (from intro)
| Type | Example |
|---|---|
| number | `28.4` |
| number string | `"13.78"` (Zirak parses these as `Decimal`) |
| datetime | `"2024-05-01T12:34:56Z"` (ISO-8601, UTC) |
| timestamp | `1714563456` (Unix seconds) |

## Rate limits
- Order placement: **20 requests per 10 seconds** (place-order page).
- Depth / trades pages warn that frequent polling "may hit rate-limit" and suggest WebSockets.
- VERIFIED-LIVE: `/v1/trades` returns `x-ratelimit-limit: 600` and `x-ratelimit-remaining`. Window `UNVERIFIED`.
- Zirak: polls conservatively, honours HTTP 429 with exponential backoff, and reads the
  `x-ratelimit-remaining` header when it's present.

## Networking note (this machine)
The system HTTPS proxy breaks TLS to Wallex. Zirak's Wallex client ignores proxy env vars by default
(`WALLEX_USE_SYSTEM_PROXY=false`).
