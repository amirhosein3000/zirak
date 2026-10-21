# Progress

_Last updated: 2026-10-21 (end of kickoff session)_

## Done
- [x] Name: **Zirak (زیرک)**. Private repo github.com/amirhosein3000/zirak (renamed from Tarazoo on 2026-10-21).
- [x] CLAUDE.md, `.env.example`
- [x] Core: Decimal models, fee/slippage maths, market precision/minimum checks
- [x] `ExchangeClient` interface, `PaperExchange`, `ReplayExchange`, live guard + hard caps
- [x] Strategy interface + 4 baselines (EMA cross, RSI reversion, grid, DCA) + `StrategySpec` rules DSL
- [x] RiskManager (sizing, max exposure, per-order cap, SL/TP, daily loss limit, cooldown), Executor, Bot ledger
- [x] Backtester (same Bot path as paper), metrics vs buy-and-hold, JSON reports
- [x] LLM layer (OpenAI-compatible + mock): Persian brief, Persian → strategy builder, trade explanations
- [x] FastAPI app, `zirak` CLI, paper bot runner, kill switch (API + CLI + KILL file)
- [x] Frontend PWA (Next.js 16, RTL, Vazirmatn, Jalali/Tehran time): market brief → Persian builder →
      backtest report (equity vs buy-and-hold, drawdown) → paper dashboard → «چرا؟» explanations → kill switch.
      Walked end to end in the browser at 375 px against the live API (2026-10-21).
- [x] Kill switch verified three ways: dashboard button, `POST /api/kill`, and `zirak kill` from another process
- [x] Dockerfiles + docker-compose.yml (api, web, recorder profile) — **untested: Docker isn't installed on this machine**
- [x] docs/spec-day.md, docs/pitch.md (Persian), README
- [x] Quality gates green: ruff, mypy --strict, 61 pytest tests, eslint, tsc, next build

## Next
1. **Unblock the exchange:** save docs into `docs/wallex-api/`, then implement `WallexClient` (public data
   first), the recorder (`zirak record`: candles at several resolutions, order-book snapshots, trades →
   SQLite) and the history backfill. Prove it with a short live run and replace the synthetic sample.
2. Live-data paper runner (`DATA_SOURCE=wallex`): PaperExchange in book mode on the real order book.
3. Prompt 1 from the prompts file (verify and harden), then prompt 2 (extra modules) and prompt 3 (strategy research).

## BLOCKED: Wallex API docs
`docs/wallex-api/` does not exist yet. Until it does:
- `WallexClient` (exchange/wallex.py) is a guarded stub: every method raises `NotImplementedError`.
- The recorder (`zirak record`) and history backfill (`zirak backfill`) exit with "BLOCKED".
- `DATA_SOURCE=wallex` is refused; everything runs on `DATA_SOURCE=replay`.
- The sample dataset in `backend/tests/fixtures/sample/` is **SYNTHETIC** (seeded random walk with a
  crash), not real data. Replace it with a short real recording once the recorder exists.

To unblock: save the developers.wallex.ir pages (REST market data, candles/history, order book,
trades, account/balances, orders, WebSocket channels, rate limits, fees) as markdown or text in
`docs/wallex-api/`, then ask Claude to implement `WallexClient` + recorder from them.

## UNVERIFIED (must be checked against the docs)
- Fee rates (`FEE_TAKER_PCT=0.25`, `FEE_MAKER_PCT=0.20`) are placeholders.
- Fee convention (fee taken from the received asset) — `fees.py`.
- Market precision / min order sizes in `markets.py` are placeholders (`Market.verified=False`).
- Candle resolution names and the history endpoint's paging limits.
- The `x-api-key` header requirement for public endpoints.

## Open issues / notes
- The recorder service in docker-compose restarts in a loop until `zirak record` is implemented (it's behind
  the `recorder` profile, so it's off by default).
- The browser preview needed CORS for port 3001; the API accepts any `localhost:<port>` origin plus `CORS_ORIGINS`.
- `liara-hackathon-prompts.md` in the repo root is the user's file; it isn't tracked and nobody has touched it.
- Backtest results on the synthetic sample are mostly negative vs buy-and-hold. That's expected and
  honest; real strategy research (prompt 3) needs real recorded data.
- Python 3.12 comes from a uv-managed interpreter
  (`C:\Users\Lotus\AppData\Roaming\uv\python\cpython-3.12.15-windows-x86_64-none\python.exe`);
  the system default is 3.14.
