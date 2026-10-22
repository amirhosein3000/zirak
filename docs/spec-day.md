# Spec day playbook

Use this the minute the official spec for «تریدر هوشمند برای والکس» is published.

## 1. Paste this prompt into a fresh Claude Code session (with the spec below it)

```
The official spec is below. Read CLAUDE.md, docs/progress.md and docs/spec-day.md first.
Do NOT write code until I approve the plan.

1. Summarise the spec in 5 bullets, including judging criteria (with weights), deliverables,
   deadline, and any rules about accounts, capital, markets, allowed APIs, LLM use, and open source.
2. Fill the mapping table from docs/spec-day.md section 2: every requirement -> already built
   (module) / needs changes / new work / out of scope. Flag ambiguities with a recommended reading.
3. Decide with me: product (UX/AI) challenge, performance (PnL/drawdown) challenge, or both?
   Recommend an effort split.
4. One-sentence product story + a 90-second demo script aimed at the highest-weight criteria.
5. Must-have / nice-to-have / cut lists (name the flags/modules to switch off).
6. Break the must-haves into parallel tasks that touch different files: files, acceptance check,
   rough time. Name the riskiest task and de-risk it first.
7. If real money is involved, confirm the risk limits (MAX_ORDER_TMN, MAX_ORDER_USDT,
   DAILY_LOSS_LIMIT_PCT) with me before anything goes live. LIVE_TRADING stays false until then.

After I approve: run independent tasks in parallel sessions, commit after each, keep the demo
working at every commit, and run all quality gates (CLAUDE.md) before calling anything done.

SPEC:
<paste spec here>
```

## 2. Spec → module map (what we already have)

| Likely requirement | Where it lives | Status |
|---|---|---|
| Connect to Wallex market data | `exchange/wallex.py`, `data/recorder.py` | Done (REST verified live; WS v2 flaky, v1 fallback) |
| Place / cancel orders on Wallex | `exchange/wallex.py` behind `exchange/guard.py` | Implemented from docs, mocked tests; **never run with real money yet** |
| Paper trading / simulation | `exchange/paper.py`, `engine/runner.py` | Done |
| Backtesting with metrics | `backtest/engine.py`, `/backtest` page | Done |
| Strategy from natural language (Persian) | `llm/builder.py`, `strategy/spec.py`, `/build` | Done (mock + LLM) |
| Market analysis / signals in Persian | `llm/brief.py`, `/` page | Done |
| Explainability ("why this trade?") | `llm/explain.py`, `TradeLog` | Done |
| Risk management | `engine/risk.py` | Done |
| Kill switch / safety | `runner.kill`, `zirak kill`, dashboard button | Done |
| Dashboard (PnL, positions, orders) | `/dashboard` | Done |
| Mobile / PWA / Persian RTL | `frontend/` | Done |
| Competition mode (headless, logs, perf file) | `modules/competition.py`, `zirak compete` | Done for **paper** (replay or live data): sleeves, team limits, `orders.csv`/`equity.csv`/`report.json`. Real-account sleeves: new work (see `docs/fake-specs/dry-run-spec-b.md`) |
| Portfolio / multi-asset rebalance | `modules/portfolio.py`, `/tools` | Done (backtest + suggestion; no auto-execution) |
| News / sentiment | `modules/news.py`, `/tools` | Done (mock or RSS; optional size reduction) |
| Alerts (Telegram/Bale) | `modules/alerts.py`, `/tools` | Done |
| Market regime detection | `modules/regime.py`, `/tools` | Done (+ regime-gated strategies) |
| Order-book intelligence, fair USDT price | `modules/orderbook.py`, `/tools` | Done |
| AI coach on past trades | `modules/coach.py`, `/tools` | Done |
| Strategy evidence | `docs/research.md`, `zirak research` | Done: nothing validated yet on 60 days of data |
| Restart safety for long live runs | — | **Missing**: bot ledger is in memory |
| Wallex sandbox / competition account | new `ExchangeClient` implementation | New, small (adapter pattern) |

## 3. Default triage

**Must (any spec):** working demo flow end to end; the not-financial-advice notice; paper mode by
default; the kill switch; honest backtest numbers vs buy-and-hold.

**Must if performance-judged:** `WallexClient` (or their sandbox client) + live data runner,
conservative preset, strict caps, a performance log file in the required format, the recorder
running from minute 0.

**Must if product-judged:** polish the 3 screens in the demo script, add `DEMO_MODE` (cached LLM
answers, replay dataset with a clear story), real LLM key configured plus a backup.

**Nice:** news sentiment, alerts, portfolio mode, AI coach.

**Cut first:** anything that needs a new external integration the spec doesn't reward.

## 4. Demo script skeleton (90 s)

1. (10 s) Problem: retail traders lose to emotion and missing risk control; grid bots are blind rules.
2. (15 s) Market screen: pick بیت‌کوین/تومان → Persian brief (trend, volatility, order-book imbalance, levels).
3. (20 s) Type «وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش» → exact rules in Persian;
   point at the safety stop-loss Zirak added and told the user about.
4. (15 s) Backtest: return vs buy-and-hold, drawdown chart, fees included; tap «چرا؟» on a trade.
5. (15 s) Start paper mode → live dashboard → a decision appears with its explanation.
6. (5 s) Kill switch: one tap, every order canceled, bot stopped.
7. (10 s) Why it matters for Wallex: safer users, more engagement and volume, explainable AI.

## 5. Parallel tasks template

| Task | Files (no overlap) | Acceptance check | Time |
|---|---|---|---|
| Adapt to new/changed Wallex docs | `exchange/wallex.py`, `tests/test_wallex_client.py` | docs map updated; guard tests pass | 1–2 h |
| Spec-required screen | `frontend/src/app/<new>/` | renders at 380 px, Persian, no console errors | 1–2 h |
| Required report/log format | `backtest/report_<spec>.py` | file validates against the spec example | 1 h |
| Demo mode + cached LLM | `llm/cache.py`, `api/main.py` | demo works with Wi-Fi off | 1–2 h |
| Pitch + demo checklist | `docs/pitch.md`, `docs/demo-checklist.md` | timed run ≤ 90 s | 1 h |
