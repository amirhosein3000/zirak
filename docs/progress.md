# Progress

_Last updated: 2026-10-21_

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
- [x] Backend quality gates green: ruff, mypy --strict, 58 pytest tests

## In progress / next
- [ ] Frontend (Next.js PWA, RTL, Vazirmatn): market brief → builder → backtest report (equity + drawdown) → paper dashboard → kill switch
- [ ] Docker Compose (backend, frontend, recorder) — can't be tested locally (Docker isn't installed)
- [ ] docs/spec-day.md, docs/pitch.md, README

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
- `liara-hackathon-prompts.md` in the repo root is the user's file; it isn't tracked and nobody has touched it.
- Backtest results on the synthetic sample are mostly negative vs buy-and-hold. That's expected and
  honest; real strategy research (prompt 3) needs real recorded data.
- Python 3.12 comes from a uv-managed interpreter
  (`C:\Users\Lotus\AppData\Roaming\uv\python\cpython-3.12.15-windows-x86_64-none\python.exe`);
  the system default is 3.14.
