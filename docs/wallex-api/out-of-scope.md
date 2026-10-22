# Out of scope: never called by Zirak

These parts of the Wallex API are kept in `raw/out-of-scope/` for reference only.

## Banking and withdrawal: FORBIDDEN (safety rule: no withdrawal/transfer code, ever)
`raw/out-of-scope/banking-and-withdrawal/`
- `POST /v1/account/money-withdrawal`: Toman withdrawal (needs a withdraw-permission key bound to an IP)
- `POST /v1/account/ibans`, `GET /v1/account/ibans`: bank IBANs
- `GET /v1/account/card-numbers`: bank cards
- `GET /v1/account/wallets/{symbol}?network=`: crypto deposit addresses

## Trading credit / prop sub-accounts
**Partly in scope since 2026-10-22:** the challenge account is a credit plan; three read-only calls are
used, see [credit-account.md](credit-account.md). Everything else below stays out of scope.
`raw/out-of-scope/trading-credit/` (guide + OpenAPI). `/sub-accounts`, `/sub-accounts/transfers`
(**transfer: forbidden**), `/v1/account/balances-detail`, `/v1/prop/packages*`, `/v1/prop/user/packages*`.
Leveraged credit packages with daily fees and liquidation limits. Each sub-account has its own API key and
needs a `sub-account-client-id` header.

## Margin (leveraged long/short)
`raw/out-of-scope/margin/` (guide + swagger). `/margin-trade/v1/...`: positions, collateral, SL/TP, loan
calculator, dry-run, long/short ratio, user PnL. Positions live up to 21 days. Leverage risk is out of
scope for a risk-first retail assistant.

## OTC / instant trade
`raw/out-of-scope/otc/` (guide + swagger). `GET /v1/otc/markets` (has `minQty`/`minNotional`/`maxNotional`),
`GET /v1/account/otc/price`, `POST /v1/account/easy-trade/orders`. Quote-based instant buy/sell.
Possible future feature; not used now.
