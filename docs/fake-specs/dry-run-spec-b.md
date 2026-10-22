# Dry run: docs/spec-day.md applied to FAKE SPEC B

_Rehearsal on 2026-10-22. Plan and task breakdown only, as on the real day. The "cheap prep" at the
end was implemented afterwards._

## 1. The spec in 5 bullets
- **Performance track.** Automated spot trading on a real Wallex competition sub-account with 50 M TMN,
  BTCTMN / ETHTMN / USDTTMN only, for 48 hours, no manual orders, documented rate limits.
- **Judging:** net PnL in Toman 50 %, max drawdown 30 %, logging/explainability 20 %.
- **Deliverables:** `orders.csv` (one row per order state change, exact header), `equity.csv` every
  5 minutes with drawdown, final `report.json` with the commit hash; repo; 1-page strategy note.
- **Timeline:** code freeze 20 h after publication; no new code after hour 24 of the window; the bot
  may be stopped at any time.
- **Accounts:** real money (small, but real): our LIVE_TRADING rules apply in full.

## 2. Requirement map
| Requirement | Status | Where / what |
|---|---|---|
| Talk to the real Wallex API with their key | Built, **never run against a real order** | `exchange/wallex.py` (LIMIT only, guard, throttle 20/10 s) |
| Spot LIMIT orders, cancel, order status | Built from docs; fields UNVERIFIED | `WallexClient.place_order/cancel_order/get_order` |
| Hard limits, kill switch, daily loss limit | Built | `exchange/guard.py`, `engine/risk.py`, `zirak kill` |
| Several strategies on **one real account** | **New work** | `modules/competition.py` runs paper sleeves only; real sleeves need per-sleeve accounting on a shared balance |
| Run unattended 48 h, survive restarts | **Needs changes** | Bot ledger is in memory: a restart forgets the position → must reconcile from balances/open orders |
| No manual orders (detect / never collide) | Needs changes | Refuse to start while the account has open orders we didn't place (cheap prep, done) |
| `orders.csv` per state change, exact header | Needs changes | Bot only logged decisions → order event log (cheap prep, done) |
| `equity.csv` every 5 min with drawdown | Needs changes | competition `equity.csv` lacked drawdown (cheap prep, done) |
| `report.json` with commit | Needs changes | final report (cheap prep, done) |
| Strategy choice | Built (thin evidence) | `docs/research.md`, preset `dip3_tp5` |
| Mark-to-market in Toman | Built | competition values USDT sleeves via USDTTMN |
| UI | Out of scope (not judged) | keep the dashboard for monitoring only |

**Ambiguities (with our reading):**
- "Max drawdown" of what? → total account value in Toman, sampled every 5 minutes (we sample more often).
- "Fees included" → use the fee from `GET /v1/account/fee` on day 0; our placeholders are UNVERIFIED.
- "Restart with new code after hour 24" → restarts with the *same* commit are allowed; plan for them.
- USDTTMN counts as a market: holding USDT is a legal "position", which matters if the Toman falls.

## 3. Product or performance?
Performance. Suggested effort: **70 % reliability and risk** (real order path, restart safety, logs),
**20 % strategy** (conservative preset, sizing for drawdown), **10 % the 1-page note**. Scoring is 50 %
PnL vs 30 % drawdown: a flat, safe bot beats a volatile one unless the market trends hard; with half the
score on PnL in Toman, discuss a USDT reserve sleeve (directional bet on the Toman) with the user.

## 4. Story + 90-second script
One sentence: *"Zirak trades small, explains every order in Persian, and can't lose more than its limits."*
Script (for the 1-page note / any presentation): limits first (per-order cap, daily loss, team drawdown,
kill switch), then the strategy (dip-buy, why it was chosen on out-of-sample data), then the logs
(a real `orders.csv` row with its Persian reason), then the result.

## 5. Must / nice / cut
- **Must:** a supervised tiny live order + cancel on day 0 (confirms UNVERIFIED fields); real-sleeve
  competition runner; restart reconciliation; exact log files; recorder running from minute 0; kill
  switch tested by hand against the real account.
- **Nice:** regime gate on entries; alerts to Telegram/Bale for fills and limit breaches (module exists).
- **Cut:** UI work, news module (`MODULES` without `news`), LLM explanations at runtime (use the
  deterministic Persian `note_fa`; no LLM in the trading loop at all).

## 6. Parallel tasks (no shared files)
| # | Task | Files | Acceptance check | Time |
|---|---|---|---|---|
| T1 | **Day-0 live probe**: tiny LIMIT far from market, read it back, cancel, read fees | none (CLI + notes in `docs/wallex-api/`) | status/fields recorded; UNVERIFIED list shrinks | 1 h (needs the key + user) |
| T2 | Real sleeves on one account | `modules/competition.py`, `engine/runner.py` | 2 sleeves on a mocked Wallex never exceed their sleeve; kill cancels all | 4–5 h |
| T3 | Restart reconciliation | `engine/bot.py` (ledger load), `engine/runner.py` | kill -9 + restart: position and open orders recovered, no double buy | 3 h |
| T4 | Spec log files | `modules/competition.py` writer only | header byte-exact; one row per state change; 5-min equity; report.json | 1 h (mostly done in prep) |
| T5 | Fee + precision from the real account | `config.py`, `markets.py` | backtests rerun with real fees | 1 h |
| T6 | Strategy note + risk numbers with the user | `docs/` | user confirms MAX_ORDER_TMN, DAILY_LOSS_LIMIT_PCT, team limits | 1 h |

**Riskiest task: T1 + T2** (real orders on a shared account, never exercised). De-risk first: T1 in the
first hour with the user watching, then T2 against a mocked Wallex before any real sleeve runs.
LIVE_TRADING stays false until the user confirms limits.

## Where we would lose the most time (honest)
1. **The real order path has never touched Wallex.** Status names, response casing, `openOrders` shape
   and fee units are UNVERIFIED. If any differ, fixes land under time pressure. Mitigation: T1 on day 0.
2. **Competition mode is paper-only.** Sharing one real balance between strategies needs new accounting
   (sleeves can't see each other's base asset; equity must not double count). ~5 hours we don't have
   spare if the spec drops late.
3. **Restarts.** A 48-hour run will restart at least once (network, laptop sleep). Today a restart
   forgets positions. That's a correctness bug in a competition, not a nicety.
4. **Data access.** Wallex was unreachable from abroad; the runner must live in Iran (or a VPS there).
5. **Fees.** Unknown fee tier changes which strategy is sensible; we can't know before the key arrives.

## Cheap preparation implemented now
- **Order state-change log**: every Bot records each order status change (`Bot.order_events`), and
  competition mode writes them to `orders.csv` with the exact header above (configurable).
- **`equity.csv` with drawdown**, and a **final `report.json`** (start/end value, PnL, max drawdown,
  trades, git commit).
- **Refuse to start a real bot while the account has open orders on that market** (manual orders or a
  previous run's leftovers would be invisible to the ledger).
