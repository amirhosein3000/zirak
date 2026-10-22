# Progress

_Last updated: 2026-10-22 (the official Wallex challenge spec arrived; the challenge agent is built)_

## The challenge (spec: docs/challenge/spec.md)
Performance + technical track: an automated, AI-driven trader on a real Wallex **credit (prop) account**
with 5,000,000 TMN for 3 days; scored 150 trading (return rank 90 — a loss scores 0 — drawdown 30,
activity 15, stability 15) + 150 technical (strategy logic 40, real AI in decisions 35, risk 30,
re-runnable 25, backtest + shadow 20). Profit must be **realised in Toman** (no coins at the end).
Deliverables: 5-min demo video, GitHub + one md document, decision logs.

### Built for it (2026-10-22)
- [x] `docs/challenge/` — verbatim spec, scoring map and plan, RUNBOOK (event days), demo-video script;
      `docs/ALGORITHM.md` — the judges' technical document
- [x] Credit account support (read-only): balances-detail, active plan's warning/liquidation limits and
      official profit, the plan's unavailable markets; transfer / close / wallet-link endpoints banned by test
- [x] **`zirak/agent/`**: causal features incl. the Toman cross-rate gap; 4 explainable setups (3 enabled);
      triple-barrier labels after fees; **ML meta-labeler** (GBM/logistic, seeded, out-of-time validated,
      EV gate + fractional Kelly, prior fallback); **LLM posture agent** with 4 read-only tools (rules
      fallback); multi-market one-account engine with account guard (daily loss, peak drawdown, liquidation
      cushion, stale data, challenge clock + flatten), hard sizing caps, maker-first entries, resting
      take-profit, live stop checks, time stops, exit TTL re-pricing, chunked exits
- [x] Backtest (walk-forward) / shadow / live share one engine; state + restart reconciliation (unknown
      orders cancelled, coins adopted); journal per run (decision log, postures, orders with latency,
      trades, equity, manifest with commit, model snapshots); report in the judges' metrics
- [x] `zirak agent verify`: every AI verdict recomputed from the logs (100 % on the sample); `export`
      (decisions.csv), `probe` (day-0 real-account check), `flatten`; `zirak mcp` read-only MCP server
- [x] Docker: `agent-shadow` / `agent-live` services (restart on crash and resume, stay down after a kill),
      image built and smoke-tested here (backtest + verify inside the container, commit recorded)
- [x] `/agent` page: results, equity, AI decisions, postures, positions, decision feed

- [x] **Liara deployment** (team account): GitHub Action `Deploy to Liara` (manual, quality gates first),
      `scripts/deploy-liara.sh`, `liara.json` for API (+ persistent disk) and web, `start.sh` runs the API plus
      the supervised agent in one container (bootstrap backfill + train on first start). Image tested here.
      Not deployed yet: the tokens weren't available to this session and Liara/Wallex aren't reachable from it.

### Honest numbers so far
Bundled real sample (1h, 60 days, placeholder fees 0.25/0.20 %), last 30 days walk-forward: +0.18 %
mark-to-market, −0.58 % realised, max drawdown 1.4 %, 12 trades. Gross of fees mean reversion and
breakouts have an edge on this data (+0.51 % / +0.40 % per trade), trend pullback and single-leg
basis trades don't. **Real fees decide the sign**; the agent reads them from the account.

### Next (needs the user / Wallex access)
1. From Iran: `zirak backfill --days-1m 45 --days-1h 180`, `zirak agent train`, `zirak agent backtest --days 14`
   on the challenge config (15m); update ALGORITHM.md §9 with the numbers.
2. API key of the credit account (trade-only), challenge start/end (UTC) in `config/challenge.json`,
   an LLM key (OpenAI-compatible) for the posture agent.
3. `zirak agent probe --yes` with the user watching; record the confirmed order fields.
4. Shadow run for hours; **user confirms the risk limits** (docs/challenge/README.md); then live.
5. After the end: report, verify, export, commit the run directories, record the video, tag `challenge-final`.

## Done (before the spec)
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
- [x] **New hero: «مانور سقوط» crash drill** (backtest page): the latest real candles + a synthetic,
      deterministic stress scenario (flash crash, slow bleed, pump-and-dump, overnight gap) played candle by
      candle: your strategy with Zirak vs the same strategy unprotected vs the emotional trader vs holding,
      live scoreboard, Persian narration ticker (stops, blocked buys, gap slippage told honestly), verdict.
      `POST /api/drill`, `backtest/drill.py`, `components/CrashDrill.tsx`. On the bundled BTCTMN sample with
      the example sentence: flash crash −27 % → Zirak −0.4 %, unprotected −1.6 %, emotional −1.8 %, hold −20.8 %.
      Honest caveat it also shows: in the slow bleed, repeated stops left the protected run slightly worse
      (−4.5 % vs −4.2 %)
- [x] Quality gates green (at the hero-feature milestone): ruff, mypy --strict, 131 pytest tests (network-free), eslint, tsc, next build

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
