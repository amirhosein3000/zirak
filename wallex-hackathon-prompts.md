# Prompts — Wallex smart trader (تریدر هوشمند برای والکس)

Model: **Claude Opus 5.5** for the kickoff and for prompts 1, 3, 4, 5 and 8, where money logic and judgment matter. **Sonnet 5.5** is fine for 2, 6 and 7.

In a fresh session, start every prompt after the kickoff with: `Read CLAUDE.md and docs/progress.md first, and update progress.md when you finish.`

Start the kickoff in plan mode, approve the plan, then let it build.

Before the kickoff (you, in Claude Code desktop):
1. Install the GitHub CLI and run `gh auth login`, so Claude Code can create the repo.
2. Create a Wallex account and an API key with **trading permission only, never withdrawal**.
3. Save the Wallex API docs pages (developers.wallex.ir: REST market data, candles, orders, account, WebSocket channels) as text or markdown into `docs/wallex-api/` in an empty project folder, and open Claude Code desktop in that folder. Claude Code should build from the real docs, not from memory; the site blocks automated tools, so you have to save them yourself.
4. Check that the Wallex API answers from the machine and country where the bot will run. If it doesn't, plan to run the data recorder on a server that can reach it.
5. Get an OpenAI-compatible LLM key, plus a backup provider.

| # | When | Purpose |
|---|------|---------|
| 0 | Now | Kickoff: engine, paper trading, data recorder, UI, one demo flow |
| 1 | Right after kickoff | Verify and harden, especially money logic |
| 2 | Before the event | Pre-build extra modules for likely spec readings |
| 3 | Before the event | Strategy research with honest backtests |
| 4 | Before the event | Dry run with fake specs |
| 5 | Spec day, minute 0 | Turn the real spec into a plan |
| 6 | When Wallex gives a sandbox, competition account or data | Plug it in |
| 7 | Last 20% of the event | Demo mode, polish, pitch |
| 8 | Any time something breaks | Emergency |

---

## 0. Kickoff

```
You are my lead engineer for a hackathon. I am a product-minded "vibe coder": I direct, you build. Work autonomously, commit often, and only stop to ask me when you are blocked (e.g. a missing API key).

### Context
- Challenge sponsored by **Wallex (والکس)**, an Iranian crypto exchange: «تریدر هوشمند برای والکس» — a smart trader for Wallex.
- The official spec is NOT published yet. Coding beforehand is allowed.
- Wallex already offers built-in bots (spot grid, infinite grid, smart rebalance, copy bots). Our entry must be clearly smarter than a rule-based grid bot: AI-assisted analysis, strategy creation in plain Persian, explainable decisions, and strong risk control.
- The spec could go two ways, and we must be ready for both:
  (a) a user-facing smart trading assistant/product, judged on UX and idea;
  (b) a bot judged on trading performance (PnL, drawdown) in a paper or real competition.
- Wallex API docs are in docs/wallex-api/. Use ONLY endpoints, fields and channels documented there. If something is unclear, mark it `UNVERIFIED` in code and tell me; never invent an endpoint. If docs/wallex-api/ is empty or missing, stop and tell me before building any exchange code.
- The docs show even market-data calls sending an `x-api-key` header, so read the key from `WALLEX_API_KEY` for every call, and make the public-data code work without the key only where the docs say that's allowed.

### Non-negotiable safety rules
- **Paper trading is the default.** Live orders require `LIVE_TRADING=true` AND a per-order size cap AND a daily loss limit AND a kill switch (one command/button that cancels all open orders and stops the bot).
- The code must never call withdrawal or transfer endpoints. Don't implement them.
- Never commit secrets. API keys only via env.
- The LLM never places orders directly. It analyses, proposes, explains and configures; a deterministic engine with hard risk limits executes.
- The UI shows a clear Persian notice that this is not financial advice.

### Architecture
- **Backend: Python 3.12 + FastAPI**, pandas/numpy for indicators and backtests. **Frontend: Next.js + TypeScript + Tailwind PWA**, full RTL Persian, Vazirmatn font, mobile-first (380px), Persian digits and Toman/USDT formatting. Code, comments and docs in English; UI copy in Persian.
- **Exchange adapter interface** `ExchangeClient`: markets, candles, order book, recent trades, live stream, balances, place/cancel order, open orders. Implementations:
  - `WallexClient`: real REST + WebSocket per docs/wallex-api (public market data first; private endpoints implemented but only used when LIVE_TRADING=true).
  - `PaperExchange`: simulates fills against the live (or recorded) order book, including Wallex fees (read the fee from config), slippage and partial fills, with a paper balance in Toman and USDT.
  - `ReplayExchange`: replays recorded data so the whole system runs offline and deterministically.
- **Data recorder**: a process that saves candles (several resolutions) and order-book snapshots/trades for the main markets (start with USDTTMN, BTCTMN, BTCUSDT, ETHTMN, ETHUSDT; config list) into SQLite/Parquet. Also backfill historical candles via the documented history endpoint. This must be easy to leave running for days before the event.
- **Strategy engine**: a `Strategy` interface (on_candle / on_book → signals), a `RiskManager` (position sizing, max exposure, stop-loss, take-profit, daily loss limit, cooldown), and an `Executor` that turns approved signals into orders on whichever ExchangeClient is active. Ship 4 baseline strategies: EMA crossover trend, RSI mean reversion, grid, DCA.
- **Backtester** using the same Strategy + RiskManager code as live (no separate logic), with fees and slippage, reporting PnL, max drawdown, Sharpe, win rate, number of trades, exposure, and buy-and-hold comparison.
- **LLM layer** behind a provider abstraction (OpenAI-compatible: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`) with `MOCK_LLM=true` returning canned answers so everything demos without keys. Uses:
  1. Market brief in Persian: current trend, volatility, order-book imbalance, key levels, for a chosen market.
  2. Natural-language strategy builder: the user writes «وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش» → the LLM outputs a validated strategy config (JSON schema) → shown to the user in plain Persian for confirmation → backtested → can run in paper mode.
  3. "Why did the bot do that?": an explanation of each trade from the logged signals and indicators.
- Docker Compose for backend + frontend + recorder; `.env.example` documenting every variable.

### Deliver, in order
1. **Name and plan first.** Propose 3 short product names that are easy to say in Persian and English and don't use "Wallex"/«والکس» as the main word; pick the best with a one-line reason. Then show me the name, architecture, folder structure, module list and milestones, and proceed after I approve.
   **Then create the GitHub repo:** run `gh auth status` (if the GitHub CLI is missing or logged out, tell me the exact command to run and wait), `git init` in this folder (docs/wallex-api/ is already here), create a **private** GitHub repo with that name via `gh repo create`, and push the first commit. Use the name in the README, app title and PWA manifest.
2. **CLAUDE.md**: stack, layout, safety rules (copy them verbatim), adapter pattern, how to add a strategy, how to run backtests, how to run paper vs live, quality gates. Written for future Claude Code sessions.
3. Exchange adapters + data recorder + historical backfill. Prove the recorder works against the real public API with a short run, and save a small sample dataset in the repo for tests.
4. Strategy engine, RiskManager, Executor, PaperExchange, ReplayExchange, 4 baseline strategies.
5. Backtester + a backtest report (JSON and a page in the UI with an equity curve and drawdown chart).
6. **Demo flow end to end**: pick a market → Persian market brief → type a strategy in Persian → see it as structured rules → backtest it → start it in paper mode → watch a live dashboard (positions, PnL, open orders, trade log with explanations) → kill switch.
7. Quality gates: ruff + mypy (or pyright), pytest, frontend lint/typecheck/build. Unit tests for fee/slippage maths, RiskManager limits, paper fills, and that LIVE_TRADING=false can never reach a real order endpoint. Run everything yourself before calling anything done.
8. docs/spec-day.md: a ready-to-use prompt for when the spec drops (map spec → modules, must/nice/cut lists, demo script, parallel tasks).
9. docs/pitch.md: pitch outline in Persian.
10. README.md in English with a short Persian summary on top.

### Working rules
- Keep the repo private, and commit and push after each milestone. Prefer simple code over clever abstractions.
- Keep `docs/progress.md` updated after every milestone: what's done, what's next, open issues. If the session's context is getting long, stop at a milestone boundary so a fresh session can continue from CLAUDE.md + progress.md.
- Use our own product name and original visuals. Do not copy Wallex's logo, brand assets or interface so the app could be mistaken for an official Wallex product; the UI can say «ساخته‌شده برای هکاتون والکس».
- Numbers: use Decimal (or integer minor units) for prices, quantities and balances; respect each market's price/quantity precision and minimum order size from the API.
- Every timestamp in UTC internally; show Tehran time in the UI.
- Finish with: what works, what is mocked, what is UNVERIFIED against the docs, and the exact commands to run the recorder, a backtest, paper trading, and the UI.
```

---

## 1. Verify and harden

```
Review the whole repo as a strict senior reviewer who has seen trading bots lose money. Read CLAUDE.md first.

1. Run every quality gate; fix all failures.
2. Safety audit: prove with tests and by reading the code that (a) no path can place a real order unless LIVE_TRADING=true, (b) no withdrawal/transfer code exists, (c) the kill switch cancels all open orders and stops the loop even if the LLM or the WebSocket is down, (d) the daily loss limit actually halts trading.
3. Money-maths audit: fees, slippage, rounding to market precision, minimum order size, Toman vs USDT conversion. Add tests for edge cases (tiny balances, partial fills, price gaps).
4. Backtest honesty audit: look for look-ahead bias, using the close of a candle that hasn't closed yet, ignoring fees, or fills at impossible prices. Fix anything found.
5. Resilience: WebSocket disconnects and reconnects, API rate limits (respect documented limits, back off on 429), stale data detection (stop trading if data is older than N seconds).
6. Walk the demo flow at 380px in Persian; fix RTL, number formatting and anything confusing.
7. Make sure CLAUDE.md matches the code.

Report what you fixed, what still worries you, and what I must test by hand.
```

---

## 2. Pre-build extra modules

```
Read CLAUDE.md first. The spec is unknown, so pre-build likely features as independent modules behind feature flags. Each must work in MOCK_LLM and paper/replay mode, follow the adapter pattern, and be removable without touching others. Commit after each.

1. Market regime detector: classifies each market as trending / ranging / high-volatility from indicators; strategies can be switched on/off per regime; shown in the UI.
2. Persian news & sentiment: pull a few public crypto news sources (RSS or official APIs only, no scraping against site rules), LLM-summarise in Persian, score sentiment, show it next to the market brief; optional input to the RiskManager (e.g. reduce size on very negative news). Mock source for offline.
3. Order-book intelligence: spread, depth imbalance, large-wall detection, and a simple "fair Toman price of USDT" indicator from USDTTMN vs. BTCTMN/BTCUSDT; shown as cards.
4. Portfolio mode: target allocation (e.g. 50% USDT / 30% BTC / 20% ETH) with smart rebalance thresholds, and a Persian explanation of each rebalance.
5. Alerts: price/indicator/PnL alerts delivered in-app and via a Telegram or Bale bot (adapter, both behind flags).
6. AI coach: reviews the user's last N trades (paper or imported) and gives Persian feedback (overtrading, no stop-loss, chasing pumps) with concrete suggestions.
7. Competition mode: a headless runner that trades a chosen set of strategies on one account with strict risk limits, logs everything, and writes a live performance file (PnL, drawdown, trades). This is our entry if the spec is a PnL competition.

Update CLAUDE.md with a "Modules" section (what, flag, files, how to remove). Run all quality gates.
```

---

## 3. Strategy research (before the event)

```
Read CLAUDE.md. Using the recorded and backfilled data, find strategies that are robust, not lucky.

1. For each baseline strategy and each main market, run a walk-forward test: optimise parameters on one window, test on the next unseen window, roll forward. Report out-of-sample results only, with fees and slippage.
2. Compare against buy-and-hold and against doing nothing (holding USDT/Toman).
3. Reject anything that only works in-sample, has fewer than 30 trades, or whose drawdown is worse than buy-and-hold.
4. Save the surviving configurations as presets with a Persian one-line description each, and a short docs/research.md with tables and the honest conclusion, including "nothing beat holding" if that's the truth.
5. Choose a default preset for competition mode with conservative risk settings, and explain the choice.
```

---

## 4. Dry run with fake specs

```
We are rehearsing spec day. Write two plausible but different fake specs for a Wallex-sponsored challenge «تریدر هوشمند برای والکس», saved in docs/fake-specs/:
- Spec A: a user-facing smart trading assistant, judged on idea, UX and AI usage, with one requirement we have NOT built.
- Spec B: a trading competition: each team gets a paper or small real account via a given API, judged on PnL and drawdown over N hours, with a required logging/report format.
Each spec: problem, required features, judging criteria, deliverables, time limit.

Run docs/spec-day.md against Spec B as we would on the real day and produce the plan and task breakdown (do not implement).
Then tell me honestly where we would lose the most time, and implement any cheap preparation you recommend.
```

---

## 5. Spec day — minute 0 (paste the real spec under it)

```
The official spec is below. Read CLAUDE.md and docs/spec-day.md first. Do NOT write code until I approve the plan.

1. Summarise the spec in 5 bullets, including judging criteria, deliverables and any rules about accounts, capital, markets, or allowed APIs.
2. Map every requirement to: already built (which module) / needs changes / new work / out of scope. Flag ambiguities with your recommended interpretation.
3. Decide with me: is this mainly a product (UX/AI) challenge or a performance (PnL) challenge? Recommend how to split effort.
4. Give the product story in one sentence and a 90-second demo script aimed at the highest-weight judging criteria.
5. Must-have / nice-to-have / cut lists (which flags to turn off).
6. Break must-haves into parallel tasks that don't touch the same files: files, acceptance check, rough time.
7. Name the riskiest task and de-risk it first. If real money is involved, confirm risk limits with me before anything goes live.

After I approve, execute the must-haves with parallel subagents where tasks are independent, committing after each and keeping the app demoable at every commit.

SPEC:
<paste spec here>
```

---

## 6. Plug in what Wallex provides (sandbox, competition account, data, new endpoints)

```
Wallex has given us access/data/docs, below. Read CLAUDE.md first.

1. Save the new docs to docs/wallex-api/ and list what differs from what we implemented.
2. Update WallexClient (or add a new ExchangeClient implementation for their sandbox/competition environment). Keep the paper and replay clients working.
3. Re-run the safety tests. If this environment uses real funds, keep LIVE_TRADING off until I confirm the risk limits.
4. Run the full demo flow and competition mode against it for 10 minutes and report errors, latency, rate-limit behaviour, and any mismatch in fees or precision.

ACCESS / DATA / DOCS:
<paste here>
```

---

## 7. Demo mode, polish, pitch (last 20%)

```
Feature freeze. Only polish, reliability and the pitch. Read CLAUDE.md and the demo script.

1. Add DEMO_MODE: the demo script runs on ReplayExchange with a pre-chosen dataset where the story is clear (e.g. a sharp drop the bot handles well), cached LLM answers for the exact demo steps, instant responses, no network dependence. Normal mode unchanged.
2. Polish the screens in the demo: loading/empty/error states in Persian, charts readable on a phone, numbers formatted, consistent spacing.
3. Deploy (Docker Compose) and give me the steps to check it from a phone on mobile data.
4. docs/pitch.md: 5–7 slides in Persian with speaker notes: problem (most retail traders lose to emotion and lack of risk control), solution, demo, results (honest out-of-sample numbers), why it matters for Wallex (engagement, volume, retention, safer users), next steps, team.
5. docs/demo-checklist.md: what to open, in what order, what to say, and the fallback if Wi-Fi, the API or the LLM fails (DEMO_MODE, screen recording).
6. If competition mode is running live: confirm risk limits, kill switch, and logging are active, and write the exact command to stop it.
7. Tag the final commit `demo-final` and push.
```

---

## 8. Emergency

```
Something is broken and we are short on time. Do not refactor.
1. If any live or competition trading is running, trigger the kill switch FIRST and confirm all open orders are cancelled.
2. Reproduce the bug and show me the error.
3. If the fix is small and safe, fix it, run the quality gates (especially safety tests), commit and push.
4. If not, find the last commit where the demo flow worked and tell me the exact command to revert; switch the broken feature off with its flag instead of deleting code.

The problem:
<describe it>
```

---

## Before the event — checklist (not prompts)
- `gh auth login` done; the private repo exists and is pushed.
- The data recorder has been running for several days, so backtests and replays have fresh, real data.
- API key has trading permission only, and no withdrawal permission.
- Kill switch tested by hand at least once.
- LLM key working from where the demo runs, plus a backup provider configured.
- Deployed URL tested on your phone on mobile data.
- A screen recording of the full demo as the last-resort backup.
- Dry run (prompt 4) done at least once, timed.
- If judges need access at submission, make the repo public or add them as collaborators.
