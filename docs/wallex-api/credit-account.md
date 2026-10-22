# Credit ("trading credit" / prop) account — the challenge account

The hackathon capital is activated as a Wallex **trading-credit plan** («طرح معامله اعتباری»; challenge
spec, docs/challenge/spec.md). Source: `raw/out-of-scope/trading-credit/` (guide + OpenAPI).

## What the guide says
- Every credit account is **fully separate** from the main account: **its own wallet, its own API key,
  its own order history**. It trades the active **spot** markets (plus instant trade / convert).
- Plans close automatically at the **liquidity (liquidation) limit**; a **warning limit** sits above it.
  In the documented example the liquidation limit is ~5.5 % below the plan's starting value.
- Plans have a daily fee (the hackathon plan's fee is unknown: UNVERIFIED).

## Endpoints Zirak uses (read-only)
| Endpoint | Use | Header |
|---|---|---|
| `GET /v1/account/balances-detail` | balances of the credit account: per asset `symbol`, `total`, `freeze`, `available` | `sub-account-client-id` (OpenAPI lists it; the description says no custom header is needed: UNVERIFIED which one is right when using the sub-account's own key, so Zirak sends it when `WALLEX_SUB_ACCOUNT_CLIENT_ID` is set) |
| `GET /v1/prop/user/packages/active` | the active plan: `packageDetail.startBalance`, `userPackageDetail.warningLimit`, `.liquidityLimit`, `.profit`, `.profitPercentage`, `.status`, `.expireAt` | `Sub-Account-Client-id` |
| `GET /v1/prop/packages/{id}` | `result.unavailableMarkets`: markets this plan may **not** trade | none |

Spot trading uses the normal spot endpoints (spot-trading.md) with the credit account's API key.
UNVERIFIED: whether spot calls also need `sub-account-client-id` (checked on day 0 with `zirak agent probe`).

## Never called (a test scans the code)
`POST /v1/prop/user/packages` (activate), `DELETE /v1/prop/user/packages` (close the plan),
`/v1/prop/user/packages/connect-to-wallet` (POST/DELETE), `/v1/prop/user/packages/enable-renew`,
`/sub-accounts`, `/sub-accounts/transfers`.
