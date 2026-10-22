# Progress

_Last updated: 2026-10-22 (prompts 1–4: hardening, modules, research, dry run)_

## Done
- [x] Name: **Zirak (زیرک)**. Private repo github.com/amirhosein3000/zirak (renamed from Tarazoo on 2026-10-21).
- [x] CLAUDE.md, `.env.example` (every variable documented)
- [x] Core: Decimal models, fee/slippage maths, market precision/minimum checks
- [x] `ExchangeClient` interface, `PaperExchange` (candle + book fill models), `ReplayExchange`, live guard + hard caps
- [x] Strategy interface + 4 baselines (EMA cross, RSI reversion, grid, DCA) + `StrategySpec` rules DSL
- [x] RiskManager, Executor, Bot ledger; backtester on the same path; metrics vs buy-and-hold
- [x] LLM layer (OpenAI-compatible + mock): Persian brief, Persian → strategy builder, trade explanations
- [x] FastAPI app, `zirak` CLI, kill switch (UI button, `POST /api/kill`, `zirak kill`, KILL file)
- [x] Frontend PWA (Next.js 16, RTL, Vazirmatn, Jalali/Tehran time), full demo flow
- [x] **Wallex API docs organized** (2026-10-22): `docs/wallex-api/README.md` maps all 46 saved pages,
      topic digests, raw pages renamed under `raw/`, 7 redundant files deleted, conflicts + gaps listed
- [x] **WallexClient** from the docs: markets (real precision), candles (1m/1h/1d native + paging; 5m/15m/4h
      aggregated), depth, trades, fair prices, balances, fees, place/cancel/get/open orders (guarded)
- [x] WebSocket stream: Centrifugo v2 with backoff, falls back to v1 (v2 handshake answered 503 often)
- [x] **Recorder + backfill** proven live: `zirak backfill` (180 d of 1h, 1000 d of 1d, 3 d of 1m for 5 markets
      in ~19 s) and `zirak record --duration 75` (0 errors: candles, order books, trades)
- [x] **Real sample dataset** in `backend/tests/fixtures/wallex` (1m/1h/1d + markets.json) is now the default
      replay data; the synthetic sample remains only for deterministic tests
- [x] **Paper trading on live Wallex data** (`DATA_SOURCE=wallex`): verified via CLI (USDTTMN 1m) and API
      (ETHUSDT 1m): fills at the real ask, fee in the received asset, kill switch cancels and stops
- [x] Live-order safety: marketable LIMIT with `LIVE_MAX_SLIPPAGE_BPS` cap, unfilled orders canceled after `LIVE_ORDER_TTL_S`
- [x] **Hero features** (2026-10-22): Zirak Score (0-100 + grade + Persian verdict), risk-shield counterfactual
      (same strategy without the risk manager), time machine (period chips incl. "worst crash" found in the
      data), strategy duel vs baselines + an emotional FOMO/panic trader + buy-and-hold, market mood gauge,
      buy/sell/blocked markers on price charts, live-money banner + shield counter on the dashboard
- [x] **Real-money mode ready (not yet used)**: `/safety` page with pre-flight checklist and typed confirmation;
      `/api/live/start`; LIMIT orders priced off the live book, capped by `MAX_ORDER_*`, canceled after a TTL;
      read-only/cancel calls need only the key. Tested end to end against a mocked Wallex.
- [x] Backtests 3-10x faster (lazy frames, numpy EMA/RSI): a 90-day 1h backtest takes ~0.7 s; duel ~5 s
- [x] **Prompt 1 — verify & harden** (2026-10-22): paper fills fixed (shared volume cap no longer resets
      to unlimited; marketable limits are takers at the touch capped by their limit, resting limits makers
      at their own price, gaps never give a better price); live orders shrink to fit `MAX_ORDER_*` after the
      protective price (before: a full-size order tripped the hard cap and killed the bot); `STALE_DATA_S`
      blocks new buys on old candles / silent feed / empty or crossed book; order placement throttled to the
      documented 20 per 10 s; open positions pay the exit fee in final metrics; kill switch proven with the
      market data down and via the KILL file; DLL proven end to end; 380 px UI walk (signed numbers in RTL,
      chart labels); lockfile synced (`npm ci` failed); CLAUDE.md matches the code
- [x] **Prompt 2 — modules** behind `MODULES` (`zirak/modules/`, `/tools` page, CLAUDE.md "Modules"):
      regime detector + regime-gated strategies, order-book intelligence + fair USDT price, news sentiment
      (mock/RSS, optional buy-size reduction), portfolio rebalancing, alerts (in-app/Telegram/Bale), AI
      coach, competition mode (`zirak compete`: paper sleeves, team drawdown / daily-loss stop via the kill
      switch, `performance.json`, `orders.csv`, `equity.csv`, `report.json`)
- [x] **Prompt 3 — research**: `zirak research` walk-forward; [docs/research.md](research.md): **0 of 75
      configurations survive** out of sample on the 60-day sample (too few trades; fees). Experimental
      presets in `strategy/presets.py`; competition default = dip-buy preset, 50 % reserve
- [x] **Prompt 4 — dry run**: `docs/fake-specs/` (spec A product, spec B 48 h contest, dry-run plan);
      cheap prep done (order state-change log, spec log files, refuse real start with stray open orders)
- [x] Quality gates green: ruff, mypy --strict, **126 pytest tests** (network-free), eslint, tsc, next build

## Demo story (real Wallex data)
Time machine on BTCTMN finds the real ~36 % crash (Ordibehesht–Tir 1405). The example sentence
«وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش» scores 82 (A): −1.2 % vs −19.3 % buy-and-hold,
max drawdown 2.3 % vs 36 %; the duel ranks it #1 of 7, the emotional trader 6th, buy-and-hold last.
_Re-check these numbers on the local DB before the pitch: they were measured before the 2026-10-22
fill/metrics fixes (expected impact small: the rule strategy uses single market orders; an open
position now pays the exit fee). On the 60-day committed sample the "worst crash" chip finds a milder
period: score 68 (B), −0.03 % vs −1.25 % buy-and-hold, max drawdown 0.6 % vs 10.1 %._

## Next
1. Leave `zirak record` running for days (or on a server in Iran), `zirak backfill` 180 days, then re-run
   `zirak research`: with 60 days nothing can reach 30 out-of-sample trades.
2. With a real API key (trade permission only): read `/v1/account/fee` and replace the fee placeholders,
   then a supervised **tiny** live test (one order far from the market, then cancel) to confirm the
   UNVERIFIED order fields below. Never without the user confirming the risk limits.
3. Biggest gaps if the spec is a real-money contest (see `docs/fake-specs/dry-run-spec-b.md`):
   **restart safety** (the bot ledger lives in memory; a restart forgets positions) and **real-account
   sleeves** for competition mode (today it is paper only).
4. Prompt 7 (DEMO_MODE, pitch polish, deploy) closer to the event.

## UNVERIFIED (docs silent or ambiguous; see docs/wallex-api/README.md)
- Spot **minimum order size / min notional**: not in the docs (placeholders: 100,000 TMN, 5 USDT).
- **Fees**: placeholders `FEE_TAKER_PCT=0.25`, `FEE_MAKER_PCT=0.20`. `GET /v1/account/fee` needs a key; the rate
  unit (fraction vs percent) is unconfirmed.
- Fee convention: fee taken from the received asset. The WS `tradeDetails` example (buy USDTTMN → fee in USDT)
  agrees, but it's not stated as a rule.
- Order **status values** beyond NEW / FILLED / CANCELED; whether `price` is required/ignored for MARKET orders
  (Zirak never sends MARKET); `openOrders` response shape (doc shows a swagger placeholder map).
- Balances: whether `value` includes `locked` (Zirak assumes value = total).
- REST rate-limit window (header `x-ratelimit-limit: 600` seen on `/v1/trades`).
- WebSocket v2 handshake reliability (HTTP 503 on quick reconnects) and whether an `Origin` header matters.

## Missing from the saved docs
Spot swagger/service pages (order endpoints' exact schemas and errors), the base-services swagger file,
a page for `GET /v1/all-fairPrice`, spot minimum order sizes, and a public fee table.

## Open issues / notes
- This cloud session could not reach `api.wallex.ir` (no route from abroad), so research used the
  committed sample; nothing here was tested against the live exchange today.
- Competition mode and the paper bot share the KILL file: `zirak kill` / `POST /api/kill` stop both.
- The machine's HTTPS proxy (127.0.0.1:10808) breaks TLS to Wallex; Wallex calls bypass proxies
  (`WALLEX_USE_SYSTEM_PROXY=false`). On a server abroad Wallex may be unreachable; run the recorder in Iran.
- `timeout -s INT` doesn't stop `zirak paper` on Windows; use `zirak kill` (KILL file) or Ctrl+C.
- `liara-hackathon-prompts.md` in the repo root is the user's file; it isn't tracked and nobody has touched it.
- Docker files are untested here (Docker isn't installed).
- Python 3.12 comes from a uv-managed interpreter; the system default is 3.14.
