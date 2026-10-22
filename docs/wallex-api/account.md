# Account (private: `x-api-key`)

## Main-wallet balances — `GET /v1/account/balances`
Sources: `raw/basics/nav-and-main-wallet-balances.txt`, `raw/account/balances.swagger-page.txt`.
`result.balances` is a **map keyed by asset**:
```json
{"result": {"balances": {"USDT": {"asset": "USDT", "faName": "تتر", "fiat": false,
  "value": "<total amount>", "locked": "<frozen for orders/withdrawals>",
  "is_dust": false, "is_digital_gold": false, "asset_png_icon": "...", "asset_svg_icon": "..."}}}}
```
Zirak: `free = value - locked`, `total = value`. Whether `value` includes `locked` is **UNVERIFIED**.
The description "amount in the main account" suggests a total.

## Fees — `GET /v1/account/fee`
Sources: `raw/account/fee.txt`, `fee.swagger-page.txt`.
`result` is a map `SYMBOL → {makerFeeRate, takerFeeRate, recent_days_sum}` (fee *rates*, i.e. fractions,
and the recent trading volume). Zirak reads this in live mode to replace the `FEE_*_PCT` placeholders.
Whether the rate is a fraction (0.0025) or a percent (0.25) is **UNVERIFIED**.

## Not used
`GET /v1/account/balances-detail` (trading-credit sub-accounts) and everything in [out-of-scope.md](out-of-scope.md).
