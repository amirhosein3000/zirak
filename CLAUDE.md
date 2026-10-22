# CLAUDE.md — Zirak (زیرک)

Zirak is a smart, explainable, risk-first trading assistant built for the Wallex hackathon
(«تریدر هوشمند برای والکس»). It analyses markets in Persian, turns a Persian trading idea into
validated rules, backtests them honestly, and runs them in paper mode, with a deterministic risk
engine and a kill switch. Read `docs/progress.md` for current status before starting work, and
update it when you finish a milestone.

## Non-negotiable safety rules (verbatim from the brief)
- **Paper trading is the default.** Live orders require `LIVE_TRADING=true` AND a per-order size cap AND a daily loss limit AND a kill switch (one command/button that cancels all open orders and stops the bot).
- The code must never call withdrawal or transfer endpoints. Don't implement them.
- Never commit secrets. API keys only via env.
- The LLM never places orders directly. It analyses, proposes, explains and configures; a deterministic engine with hard risk limits executes.
- The UI shows a clear Persian notice that this is not financial advice.

Also from the brief:
- Use ONLY endpoints, fields and channels documented in `docs/wallex-api/`. If something is unclear,
  mark it `UNVERIFIED` in code and tell the user. Never invent an endpoint. If the docs are missing,
  stop before writing exchange code.
- Every Wallex call reads the key from `WALLEX_API_KEY` (`x-api-key` header); public data works
  without the key only where the docs say so.
- Money is `Decimal` (never float); respect each market's price/qty precision and minimum order.
  Indicators may use floats.
- Timestamps are UTC internally; the UI shows Tehran time.
- Own name and visuals only: don't copy Wallex branding. The UI may say «ساخته‌شده برای هکاتون والکس».

## Stack and layout
- Backend: Python 3.12, FastAPI, pandas/numpy, pydantic. Package `backend/zirak`, venv `backend/.venv`.
- Frontend: Next.js 16 (App Router) + TypeScript + Tailwind v4, RTL Persian, Vazirmatn, PWA, in `frontend/`.
- Code, comments and docs in English; UI copy in Persian.

```
backend/zirak/
  config.py        Settings from env (.env.example documents every variable)
  models.py        Decimal domain types: Market, Candle, OrderBook, Order, Fill, ...
  fees.py          fee + slippage maths (fee taken from the received asset — UNVERIFIED)
  markets.py       market metadata: real precision from Wallex (markets.json); min order value is a placeholder
  indicators.py    EMA/RSI/ATR/... on pandas
  i18n.py          Persian digits, number formatting, Tehran time
  exchange/        base.py (ExchangeClient), guard.py (live-trading choke point),
                   wallex.py (real REST client), wallex_ws.py (WebSocket stream, v2 -> v1 fallback),
                   paper.py (simulated fills), replay.py (offline data)
  data/            store.py (SQLite + CSV), source.py (recorded DB vs CSV sample), recorder.py (recorder +
                   backfill), aggregate.py (1m->5m/15m, 1h->4h), synthetic.py
  strategy/        base.py (Strategy, Signal, StrategyContext), baseline.py (4 strategies),
                   spec.py (StrategySpec DSL + RuleStrategy), registry.py
  engine/          risk.py (RiskManager), executor.py, bot.py (one strategy on one market), runner.py (paper bot + kill switch)
  backtest/        engine.py (replays through the same Bot), metrics.py, insights.py (score, shield,
                   time machine), drill.py (crash drill), walkforward.py (research)
  llm/             provider.py (OpenAI-compatible + mock), brief.py, builder.py, explain.py
  modules/         optional features behind the MODULES flag (see "Modules" below)
  api/main.py      FastAPI app
  cli.py           `zirak` command
backend/tests/     pytest; fixtures/wallex = REAL Wallex sample (default replay data),
                   fixtures/sample = SYNTHETIC candles (deterministic unit tests only)
frontend/src/      app/ (pages), components/, lib/ (api client, fa formatting)
docs/              progress.md, spec-day.md, pitch.md,
                   wallex-api/ (README.md = map of the exchange docs; topic digests; raw/ = original pages)
```

## Adapter pattern
Read `docs/wallex-api/README.md` before touching exchange code: it maps every documented endpoint,
lists what was verified live, where the docs contradict each other, and what is missing.

Everything trades through `ExchangeClient` (`exchange/base.py`):
- `WallexClient` — the only `is_real = True` client (`https://api.wallex.ir`; httpx with
  `trust_env=False` because the local proxy breaks TLS to Wallex). Public data needs no key. Every
  private method calls `guard.require_live()` first (cancels/reads use `risk_reducing=True` so the kill
  switch can still cancel). It only places LIMIT orders; the Executor turns live "market" signals into
  marketable LIMIT orders capped at `LIVE_MAX_SLIPPAGE_BPS`, and the Bot cancels them after
  `LIVE_ORDER_TTL_S`. Orders are shrunk to fit `MAX_ORDER_*` at the protective price, and
  `place_order` throttles itself to the documented 20 orders / 10 s. Order fills are tracked by polling `GET /v1/account/orders/{clientOrderId}` (the
  private WebSocket needs a browser cookie). No withdraw/transfer method, ever (a test scans the code).
- Candles: Wallex only serves 1m / 1h / 1d reliably (`udf/history` resolutions `1`, `60`, `1D`, paged
  backwards); 5m / 15m / 4h are aggregated locally (`data/aggregate.py`).
- `PaperExchange(data=<any client>)` — simulated fills. Candle mode: orders placed after candle t
  fill on candle t+1 (market at open ± slippage; a limit that is marketable on arrival fills as taker
  at the open, capped by its limit; a resting limit fills as maker at its own price only when price
  trades *through* it); all orders on a candle share one volume-participation cap (partial fills).
  Book mode: market orders walk the book; first-pass crossing limits are takers at the level price.
- `ReplayExchange` — recorded/sample data behind a time cursor that only exposes *closed* candles.
- `Executor` re-checks `require_live` + `check_hard_limits` for any real client (belt and braces).

Data flow per closed candle (`engine/bot.py`): paper matching → sync fills into the ledger →
RiskManager day roll / daily loss limit → SL/TP → strategy signals → `RiskManager.review` →
`Executor` → log entry (signal, indicators, decision, fill, PnL) for "why did the bot do that?".

## Modules (optional, `MODULES` env flag; default all)
Each module is one backend file in `zirak/modules/` exposing `router` (mounted at `/api/m/<name>`),
one test block in `tests/test_modules.py`, and one card in `frontend/src/components/modules/`
shown on `/tools` only when `/api/modules` lists it. Modules read data through the API `State`,
work offline (MOCK_LLM, replay data), and never place orders (competition runs paper bots).
To switch one off: drop its name from `MODULES`. To remove it: delete its file, test block, entry in
`modules/__init__.py` `AVAILABLE`, and its card (a missing file is treated as switched off).

| Module | What | Extra flags | Files |
|---|---|---|---|
| `regime` | trending/ranging/volatile; `RegimeGated` blocks entries outside allowed regimes | — | `modules/regime.py`, `RegimeCard.tsx` |
| `orderbook` | spread, depth, imbalance, walls, fair Toman price of USDT | — | `modules/orderbook.py`, `BookCard.tsx` |
| `news` | mock or RSS/Atom headlines, keyword sentiment, Persian summary | `NEWS_SOURCE`, `NEWS_RSS_URLS`, `NEWS_RISK` | `modules/news.py`, `NewsCard.tsx` |
| `portfolio` | target allocation + threshold rebalancing backtest, `/suggest` | — | `modules/portfolio.py`, `PortfolioCard.tsx` |
| `alerts` | price/RSI/bot-PnL alerts, in-app + Telegram/Bale | `ALERTS_*` | `modules/alerts.py`, `AlertsCard.tsx` |
| `coach` | deterministic trade-habit findings, Persian feedback | — | `modules/coach.py`, `CoachCard.tsx` |
| `competition` | multi-strategy paper sleeves, team limits, `performance.json` | — | `modules/competition.py`, `zirak compete`, `CompetitionCard.tsx` |

The only core hooks modules use: `RiskManager.size_factor` (0..1, shrinks new buys; news) and
`ReplayExchange.fork()` (independent cursor; competition).

## How to add a strategy
1. Subclass `Strategy` in `strategy/` (see `baseline.py`): set `key`, `title_fa`, `description_fa`,
   `warmup`; implement `on_candle(ctx) -> list[Signal]`. Use only `ctx.df` (closed candles).
   BUY `size_pct` = % of equity; SELL `size_pct` = % of position. Write a Persian `note_fa` and fill
   `indicators` so trades can be explained.
2. Don't put stops or sizing limits in the strategy — RiskManager owns those.
3. Register it in `strategy/registry.py` (`STRATEGIES` + `DEFAULT_PARAMS`).
4. Add a test (at least: it trades on the sample data and never sees unclosed candles).

## Commands (from `backend/`, venv active or prefix `.venv/Scripts/` — `.venv/bin/` on Linux/macOS)
```bash
zirak data-stats                                   # what data is available
zirak backtest --strategy ema_cross --symbol BTCTMN --resolution 1h
zirak backtest --spec '{"symbol":"BTCTMN","entry":[{"kind":"drop_from_high","pct":5,"lookback":24}],"position_size_pct":10,"take_profit_pct":3,"stop_loss_pct":5}'
zirak paper --strategy rsi_reversion --symbol ETHTMN --speed 0.2   # headless paper bot on replayed data
zirak compete [--config cfg.json] [--speed 0.2]    # competition mode (paper, team limits, perf file)
zirak kill                                         # KILL SWITCH (KILL file + API call)
zirak reset-kill
zirak serve --reload                               # API on :8000
zirak make-sample                                  # regenerate the SYNTHETIC sample
zirak backfill                                     # Wallex history -> data/zirak.sqlite (+ markets.json)
zirak record [--duration 600]                      # live recorder (candles, books, trades); runs for days
zirak export-sample                                # DB -> backend/tests/fixtures/wallex CSVs
```
Frontend (from `frontend/`): `npm run dev` (http://localhost:3000; reads `NEXT_PUBLIC_API_URL`).

## Paper vs live
- Paper (default): `LIVE_TRADING=false`. Backtests and the paper bot use `PaperExchange`.
  `DATA_SOURCE=replay` replays recorded data (DB, else the real sample) — works offline.
  `DATA_SOURCE=wallex` = paper trading on LIVE Wallex data: signals on real closed candles, paper fills
  walk the real order book (`BotRunner._live_loop`, polls every `LIVE_POLL_S`).
  Stale data (candle closed > `STALE_DATA_S` ago, silent feed, empty/crossed book) blocks new buys;
  10 consecutive data failures stop the bot via the kill path.
- Live money: `LIVE_TRADING=true`, `MAX_ORDER_TMN`,
  `MAX_ORDER_USDT`, `DAILY_LOSS_LIMIT_PCT`, `WALLEX_API_KEY`, and no KILL file. `/api/health`
  lists any remaining `live_blockers`. Never turn live on without the user confirming risk limits.

## Quality gates (run all before calling anything done)
```bash
cd backend && .venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check . \
  && .venv/Scripts/mypy.exe zirak tests && .venv/Scripts/python.exe -m pytest -q
cd frontend && npm run lint && npx tsc --noEmit && npm run build
```
Must-keep tests: fee/slippage maths (`test_fees.py`), RiskManager limits (`test_risk.py`), paper
fills (`test_paper.py`), live guard / no withdraw code (`test_live_guard.py`), no look-ahead
(`test_backtest.py`), the API demo flow including the kill switch (`test_api.py`), Wallex parsing and
"no request when live is off" (`test_wallex_client.py`), recorder / data / protective limits
(`test_recorder_and_data.py`), live-data paper runner + kill (`test_live_runner.py`).
Tests never touch the network (httpx MockTransport).

## Conventions
- Prefer simple code over clever abstractions. Commit and push after each milestone.
- Persian user-facing strings may be generated in the backend (signals, briefs, explanations) —
  use `i18n.fa_num`/`fa_pct` for numbers.
- Anything not confirmed by `docs/wallex-api/` is marked `UNVERIFIED` in code and listed in progress.md.
