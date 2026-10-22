# Zirak (زیرک)

> **زیرک — معامله‌گر هوشمندی که دلیل هر کارش را می‌گوید.**
> زیرک بازار را به زبان فارسی تحلیل می‌کند، ایدهٔ معاملاتی شما را از یک جملهٔ فارسی به قانون‌های دقیق تبدیل می‌کند،
> آن را صادقانه (با کارمزد و لغزش قیمت) بک‌تست می‌کند و در حالت کاغذی اجرا می‌کند؛ با مدیریت ریسک سخت‌گیرانه و کلید توقف اضطراری.
> هوش مصنوعی فقط تحلیل و پیشنهاد می‌دهد؛ هیچ سفارشی را خودش ثبت نمی‌کند. **این ابزار توصیهٔ مالی نیست.**
> ساخته‌شده برای هکاتون والکس؛ محصول مستقل و غیررسمی.

## Wallex challenge entry: the Zirak trading agent

> **عامل معاملاتی زیرک برای چالش والکس:** هر کندل، الگوهای قابل‌توضیح فرصت می‌سازند؛ یک **مدل یادگیری ماشین**
> (متا-لیبلینگ با برچسب سه‌مانعی و ارزش مورد انتظار بعد از کارمزد) دربارهٔ هر فرصت تصمیم می‌گیرد و حجم را تعیین
> می‌کند؛ یک **عامل مدل زبانی با ابزار** هر ساعت وضعیت ریسک هر بازار را تنظیم می‌کند؛ و لایهٔ ریسک قطعی با سقف‌های
> سخت اجرا را کنترل می‌کند. همه‌چیز پیش از پایان چالش به تومان برمی‌گردد و دلیل هر تصمیم ثبت می‌شود.

| Read this | For |
|---|---|
| [docs/ALGORITHM.md](docs/ALGORITHM.md) | **The technical document for the judges**: architecture, AI use, Wallex tools, buy/sell rules, risk, re-running |
| [docs/challenge/README.md](docs/challenge/README.md) | The spec, the scoring map and the plan ([official text](docs/challenge/spec.md)) |
| [docs/challenge/RUNBOOK.md](docs/challenge/RUNBOOK.md) | The 3 event days, step by step (backfill, train, shadow, probe, live, kill, deliverables) |
| [docs/challenge/demo-video.md](docs/challenge/demo-video.md) | The 5-minute demo video script |

```bash
cd backend && pip install -e ".[dev]"
zirak agent backtest --config config/sample-1h.json --days 30   # offline, on the bundled real Wallex sample
zirak agent verify ../data/runs/<run>                           # recompute every AI decision from the logs
zirak agent shadow                                              # live Wallex data, paper orders (needs access to Wallex)
```
Docker: `GIT_COMMIT=$(git rev-parse HEAD) docker compose --profile shadow up -d --build` (`--profile live` for real orders).
The web app's `/agent` page shows any run: results, equity, AI decisions, postures, positions, decision log.

## The original assistant

Zirak is a smart, explainable, risk-first trading assistant built for the Wallex hackathon
(«تریدر هوشمند برای والکس»). It is meant to be clearly smarter than a rule-based grid bot:

- **Persian market brief** — trend, volatility, order-book imbalance and key levels, phrased by an LLM from
  deterministically computed facts (or a template when no LLM is configured).
- **Strategy from one Persian sentence** — text → validated `StrategySpec` JSON → plain-Persian rules the
  user confirms → backtest → paper trading. A safety stop-loss is added (and announced) when missing.
- **Explainable decisions** — every signal is logged with its indicators and the risk manager's verdict;
  «چرا این کار را کرد؟» explains any trade, including ones the risk manager rejected.
- **Risk first** — position sizing, max exposure, per-order cap, stop-loss / take-profit, daily loss
  limit, cooldown, market precision and minimums; a one-tap kill switch (UI, API, CLI and a KILL file).
- **Honest backtests** — the same Bot/Strategy/RiskManager code as paper trading, fills on the *next*
  candle, fees, slippage, volume-limited partial fills, compared against buy-and-hold; walk-forward
  research reports out-of-sample results only ([`docs/research.md`](docs/research.md)).
- **Optional modules** (`MODULES` flag, `/tools` page) — market regime, order-book intelligence and the
  fair Toman price of USDT, news sentiment, portfolio rebalancing, alerts (Telegram/Bale), an AI trading
  coach, and a headless competition mode with team risk limits and audit logs.

## Status

See [`docs/progress.md`](docs/progress.md). In short: the whole demo flow works offline on a **real
Wallex sample** (bundled), or on **live Wallex prices** with `DATA_SOURCE=wallex` (paper money; fills
walk the real order book). The recorder and history backfill run against the public Wallex API.
Exchange code follows [`docs/wallex-api/`](docs/wallex-api/README.md) only; anything the docs don't
confirm is marked `UNVERIFIED`.

## Quick start (Windows, from the repo root)

```bash
# backend (Python 3.12)
py -3.12 -m venv backend/.venv          # or point at any Python 3.12
backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"
cp .env.example .env                     # defaults: paper trading, mock LLM, replay data

# API on :8000
cd backend && .venv/Scripts/zirak.exe serve

# frontend on :3000 (second terminal)
cd frontend && npm install && npm run dev
```

On macOS/Linux use `backend/.venv/bin/...` instead of `Scripts/...exe`.

## Commands

| What | Command (from `backend/`) |
|---|---|
| List available data | `zirak data-stats` |
| Backtest a baseline | `zirak backtest --strategy ema_cross --symbol BTCTMN --resolution 1h` |
| Backtest a rules spec | `zirak backtest --spec spec.json` |
| Headless paper bot (replay) | `zirak paper --strategy rsi_reversion --symbol ETHTMN --speed 0.2` |
| Walk-forward research | `zirak research` (writes `docs/research-results.json`) |
| Competition mode (paper) | `zirak compete [--config cfg.json]` (files in `data/competition/<name>/`) |
| Challenge agent | `zirak agent train / backtest / shadow / live / report / verify / export / probe / flatten` |
| MCP server (read-only tools for AI agents) | `zirak mcp` |
| **Kill switch** | `zirak kill` (then `zirak reset-kill`) |
| API server | `zirak serve --reload` |
| Backfill Wallex history | `zirak backfill` (1m: 3 days, 1h: 180 days, 1d: 1000 days by default) |
| Record live market data (days) | `zirak record` (status: `data/recorder_status.json`) |
| Paper trading on live prices | `DATA_SOURCE=wallex zirak paper --strategy rsi_reversion --symbol BTCTMN` |
| Docker | `docker compose up --build` (recorder: `--profile recorder`) — untested so far |

Baseline strategies: `ema_cross`, `rsi_reversion`, `grid`, `dca`. Reports are saved to `data/reports/`.

## Safety model

- Paper trading is the default. Real orders require `LIVE_TRADING=true` **and** `MAX_ORDER_TMN` **and**
  `MAX_ORDER_USDT` **and** `DAILY_LOSS_LIMIT_PCT` **and** `WALLEX_API_KEY` **and** the kill switch not engaged.
  All of it is enforced in one place (`backend/zirak/exchange/guard.py`) and checked again in the Executor.
- No withdrawal or transfer code exists; a test scans the codebase to keep it that way.
- The LLM only analyses, proposes and explains; a deterministic engine with hard limits executes.
- Secrets come only from the environment (`.env` is git-ignored; see `.env.example`).

## Layout

```
backend/   FastAPI + engine (Python 3.12)      → see CLAUDE.md for the module map
frontend/  Next.js 16 PWA, RTL Persian, Vazirmatn
docs/      progress.md, spec-day.md, research.md, pitch.md (Persian), fake-specs/ (rehearsal),
           wallex-api/ (exchange docs)
```

## Quality gates

```bash
cd backend && .venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check . && .venv/Scripts/mypy.exe zirak tests && .venv/Scripts/python.exe -m pytest -q
cd frontend && npm run lint && npx tsc --noEmit && npm run build
```
