# Zirak trading agent — algorithm, AI, risk and how to re-run it

> **خلاصهٔ فارسی.** موتور معاملاتی زیرک برای چالش والکس یک «عامل» چندلایه است که در هر کندل بسته‌شده
> این کارها را انجام می‌دهد: (۱) چند الگوی قابل‌توضیح (بازگشت به میانگین، شکست سقف با حجم، جاماندن بازار تومانی
> از نرخ جهانی) فرصت‌های «کاندید» می‌سازند؛ (۲) یک **مدل یادگیری ماشین (متا-لیبلینگ)** که روی نتیجهٔ واقعی
> هزاران کاندید گذشته (با کارمزد و لغزش) آموزش دیده، برای هر کاندید احتمال رسیدن به حد سود قبل از حد ضرر را
> پیش‌بینی می‌کند و فقط وقتی «ارزش مورد انتظار بعد از کارمزد» مثبت باشد ورود را تأیید و حجم را با کسری از معیار
> کلی تعیین می‌کند؛ (۳) یک **عامل مدل زبانی با ابزار** (Agentic) هر ساعت با فراخوانی ابزارها (وضعیت بازار، سبد،
> تصمیم‌های اخیر، کارنامهٔ مدل) برای هر بازار «وضعیت ریسک» تعیین می‌کند (عادی/محتاط/پرهیز، ضریب حجم، الگوهای
> مجاز)؛ (۴) لایهٔ ریسک قطعی با سقف‌های سخت (ریسک هر معامله ۰٫۶٪، سقف هر موقعیت ۳۰٪، سقف کل ۷۰٪، سقف هر
> سفارش، زیان روزانه، افت از اوج، فاصله تا حد لیکوییدی طرح اعتباری) و (۵) اجرای میکر-اول با حد سود از پیش ثبت‌شده،
> حد ضرر فعال و توقف زمانی. هیچ‌کدام از لایه‌های هوش مصنوعی نمی‌توانند از سقف‌های سخت عبور کنند یا مستقیم سفارش
> ثبت کنند. پیش از پایان چالش همه‌چیز به تومان تبدیل می‌شود (سود تحقق‌یافته). برای هر تصمیم — چه خرید و چه رد کردن —
> یک رکورد کامل (سیگنال، ورودی‌ها و خروجی مدل، وضعیت عامل، اندازه‌گیری ریسک و دلیل فارسی) ثبت می‌شود و فرمان
> `zirak agent verify` همهٔ تصمیم‌های هوش مصنوعی را از روی همین لاگ‌ها دوباره محاسبه و تطبیق می‌دهد.

This is the technical document for the judges of the Wallex challenge (spec: [challenge/spec.md](challenge/spec.md),
our reading: [challenge/README.md](challenge/README.md)). Run book for the event: [challenge/RUNBOOK.md](challenge/RUNBOOK.md).

## 1. What it is
An automated spot trader for Wallex Toman markets. It is long-only (spot), trades several markets from one
account (the challenge's credit account), decides on every closed candle (15 minutes in the challenge
config), manages exits continuously, and converts everything back to Toman before the challenge ends,
because the challenge scores **realised** Toman.

The same engine runs in three modes, so what we backtest and shadow-test is exactly what trades:

| Mode | Market data | Orders | Command |
|---|---|---|---|
| Backtest | history (recorded / backfilled Wallex candles) | simulated fills, next candle, fees, slippage, volume cap | `zirak agent backtest` |
| Shadow test | live Wallex REST | paper fills against the **real order book** | `zirak agent shadow` |
| Live | live Wallex REST | real LIMIT orders on the credit account | `zirak agent live` |

## 2. Architecture
```
 Wallex REST: candles (1m→15m), depth, balances-detail, plan limits, fees
        │
        ▼
 Feature engine (features.py) ── causal, scale-free: returns, RSI, Bollinger %b, ATR %, EMA gaps/slope,
        │                         volume z, distance from 96-bar high/low, trend efficiency, time of day,
        │                         Toman cross-rate gap (XTMN vs XUSDT × USDTTMN)
        ▼
 Setup scanners (setups.py) ──► candidates with their own take-profit / stop / time limit + Persian reason
        │
        ▼
 ML meta-labeler (model.py) ──► P(win) after costs, EV, fractional-Kelly size  ──┐
 LLM posture agent (posture.py, tools.py) ──► per-market stance / multiplier / setups ┤
        │                                                                          ▼
 Account guard + risk sizing (engine.py) — hard limits the AI cannot exceed ──► Execution
        │                                                                          │
        ▼                                                                          ▼
 Journal (journal.py): decisions, postures, orders (latency), trades, equity, state, model snapshots
```
Code: `backend/zirak/agent/`. Exchange access: `backend/zirak/exchange/wallex.py` (guarded; see §6).

## 3. How AI is used (and what it is *not* allowed to do)
Two AI components take part in **every** trading decision. Neither is decoration, and neither can bypass the
deterministic limits.

### 3.1 ML meta-labeler — decides whether to take each candidate, and how big
*Meta-labeling* (López de Prado): explainable rules propose trades; a classifier learns which of those
proposals actually work, given the market context.

- **Labels** (`labeling.py`): for every historical candidate, a triple-barrier simulation: entry at the next
  candle's open plus slippage; stop hit if the low reaches it (gaps fill at the worse open); take-profit if
  the high trades *through* it; otherwise exit at the close after `max_bars`. If both barriers fall in one
  candle, the stop is assumed first. Label = 1 if the **net** return after taker/maker fees and slippage is > 0.
- **Inputs**: the 22 features above + the candidate's own take-profit and stop distance + its setup.
- **Model**: gradient-boosted trees (≥ 600 labelled candidates) or a regularised logistic regression
  (fewer), fixed seeds. Validation is **out-of-time**: fit on the first 70 %, measure AUC and the EV of the
  trades it would take on the last 30 %, then refit on everything. The model card is saved with each run.
- **Decision**: `EV% = p·(tp − cost) − (1 − p)·(sl + cost)`. Take only if `EV ≥ 0.05 %` and `p ≥ 0.5`.
  Size multiplier = fractional Kelly `f = p − (1 − p)/b` (b = (tp − cost)/(sl + cost)), scaled by `f / 0.25`,
  clipped to [0, 1]. `cost` is the real round-trip cost from the account's fee tier.
- **Retraining**: every 24 h on the last 45 days (walk-forward in backtests: only candidates whose outcome
  was already known at that moment). Every model a run uses is stored under `runs/<run>/models/<model_id>/`.
- **Little data**: below 120 labelled candidates the model falls back to each setup's smoothed historical
  win rate (prior 45 %), and every decision record says `source: prior`.

### 3.2 LLM posture agent — decides how much risk each market deserves right now (agentic, tool use)
Every hour an LLM (any OpenAI-compatible provider, `temperature 0`) runs a tool-calling loop (≤ 6 steps) with
four read-only tools: `get_market_snapshot(symbol)` (trend, momentum, volatility, cross-rate gap, order-book
spread and imbalance), `get_portfolio()` (equity, drawdown, today's P&L, positions, guard state),
`get_recent_decisions(limit)` and `get_model_stats()` (the meta-labeler's model card). It returns, per market:
`stance` (normal / cautious / avoid), `risk_multiplier` (0–1.5) and `allowed_setups`, plus a Persian reason.

Its output is parsed strictly: unknown markets/setups are dropped, the multiplier is clamped, "avoid"
forces 0. The posture multiplies the ML size and can veto setups; it **cannot** place orders, move stops,
or exceed any hard cap. Every posture (with its tool calls) is logged in `postures.jsonl`.
Without an LLM key (or on any failure) a deterministic regime posture is used (`source: rules`):
volatility ≥ 2× normal → cautious, ×0.5, mean-reversion only; orderly downtrend → cautious, ×0.5, no
breakouts; orderly uptrend → all setups; otherwise → reversal setups and breakouts.

### 3.3 Wallex tools and MCP
- **Wallex API** (only documented endpoints, mapped in [wallex-api/README.md](wallex-api/README.md)): public
  `udf/history` candles, `depth`, `markets`; private `orders` (place / get / cancel / open orders),
  `account/fee`; for the challenge's credit account the read-only `balances-detail`, the active plan's
  limits (`prop/user/packages/active`) and the plan's `unavailableMarkets` ([wallex-api/credit-account.md](wallex-api/credit-account.md)).
  No withdrawal, transfer or plan-closing code exists; a test scans the codebase for it.
- **MCP**: `zirak mcp` serves Zirak's own read-only tools (market snapshot, runs, reports, decisions, explain,
  verify, model card) to any MCP agent, so an AI assistant can audit the trader live. The organisers'
  Wallex MCP is not part of our documented API set yet; when it is available it plugs into the agent's
  read-only tool layer (`tools.py`). Orders always go through the guarded engine, never through a tool.

## 4. When it buys and when it sells
### Buy: all of the following, on a closed candle
1. A **setup** fires (`setups.py`; long only):

| Setup | Condition (closed candle) | Take-profit / stop / time |
|---|---|---|
| Mean reversion | close below the lower Bollinger band (20, 2σ) **and** RSI(14) < 32 **and** 96-bar return > −12 % (not a crash) | 2 × ATR / 2 × ATR / 16 bars |
| Breakout | close above the previous 48-bar high **and** volume z-score > 1 **and** trend efficiency > 0.25 **and** volatility < 2.5× normal | 3 × ATR / 1.5 × ATR / 24 bars |
| Basis reversion | the Toman market trades ≥ 0.35 % below its usual gap to `XUSDT × USDTTMN` **and** the cross rate moved ahead over the last 4 bars | 1.5 × gap / 1.5 × gap / 6 bars |
| Trend pullback *(off in the challenge config)* | close > EMA50 > EMA200, EMA50 rising, low touched EMA20 and closed above it, RSI 40–60 | 2.5 × ATR / 1.5 × ATR / 24 bars |

   Take-profit is never below 2.5 × the round-trip cost; stops are kept between 0.6 % and 4 %.
2. The **meta-labeler** approves it (EV after costs ≥ 0.05 %, p ≥ 0.5).
3. The **posture** allows this setup in this market (stance ≠ avoid, multiplier > 0).
4. The **account guard** is `ok` (§5), the market isn't in a post-stop cooldown, there's no open position or
   pending entry in it, and fewer than 3 positions are open.
5. **Sizing** leaves a valid order above the market minimum (§5).

Candidates are ranked by EV; the best ones fill the free position slots. Every candidate (taken or skipped)
is logged with the reason.

### Sell
- **Take-profit**: a resting LIMIT sell placed right after the entry fills (maker fee).
- **Stop-loss**: live/shadow check the best bid every 5 s; backtests on the candle low. Exit with a
  marketable LIMIT (worst price = touch − 0.4 %), re-priced if not filled within 45 s.
- **Time stop**: after the setup's `max_bars`.
- **Guard**: drawdown kill, liquidation-cushion kill, or the challenge end → everything is sold.
- **Challenge end**: no new entries in the last 4 h; orderly exits from T−90 min; marketable exits from T−30 min.

## 5. Risk and capital management (hard, deterministic)
| Limit | Value (challenge config) | Where |
|---|---|---|
| Risk per trade (loss if the stop hits) | 0.6 % of equity × ML size × posture | `Agent.size` |
| Max position in one market | 30 % of equity | `Agent.size` |
| Max total exposure | 70 % of equity | `Agent.size` |
| Max simultaneous positions | 3 | `Agent.enter` |
| Cash buffer | 1 % of cash never spent | `Agent.size` |
| Per-order hard cap | `MAX_ORDER_TMN` (env), checked again before every real order | `Agent.size`, `guard.check_hard_limits` |
| Stop-loss on every position | yes (0.6–4 %) | `Agent.on_bar`, `on_tick` |
| Daily loss | 2.5 % → no new entries until the next UTC day | `check_guard` |
| Drawdown from peak | 5 % → no new entries; 8 % → sell everything + kill switch | `check_guard` |
| Credit-plan liquidation | < 60 % of the cushion (start − liquidation limit) left → no entries; < 30 % → sell everything + kill | `check_guard` (limits read from Wallex) |
| Cooldown after a stop | 4 bars in that market | `Agent._close` |
| Stale data | live: no new closed candle for one bar + `STALE_DATA_S` → no new entries (exits continue); 20 consecutive data errors → kill | `runner.run_live`, `check_guard` |
| Live-trading gate | `LIVE_TRADING=true` + `MAX_ORDER_TMN` + `MAX_ORDER_USDT` + `DAILY_LOSS_LIMIT_PCT` + API key + no KILL file | `exchange/guard.py` |
| Kill switch | `zirak kill` / KILL file / API: cancel all orders, stop. `zirak agent flatten`: sell all to Toman | `runner.kill`, `cli.cmd_flatten` |

Wash trading / self-trading is impossible by construction: one account, long-only, one position per market,
no order ever crosses our own resting order (exits cancel the take-profit first).

## 6. Execution
- **Maker-first entries**: LIMIT buy 5 bps below the last price; cancelled after 180 s (live) or one bar
  (backtest) if unfilled, and logged as `entry_unfilled`.
- **Real orders are LIMIT only.** "Market" exits become marketable limits capped by `max_slippage_bps`;
  exits larger than the per-order cap are split.
- Idempotent `client_id`s (`zirak_<random>`), Wallex's documented 20 orders / 10 s throttle, read retries
  with backoff on 429/5xx, POSTs never blindly retried.
- **Speed**: each order's acknowledgement time (`orders.jsonl: ack_ms`) and each bar's close→decision latency
  (`bars.jsonl`) are measured and summarised in the report.

## 7. Reliability
- State (`state.json`) is rewritten atomically after every change; restarting the same command resumes the run.
- On a live (re)start the account is the source of truth: unknown open orders are cancelled, positions whose
  coins are gone are dropped, coins without a position are adopted with a stop.
- Errors in one call never stop the loop; they are counted (stability metric) and journaled.
- Docker: `agent-live` / `agent-shadow` restart on a crash and resume; after the kill switch they stay down.
- Every run's manifest records the git commit (or the image's `ZIRAK_COMMIT`): the code that traded.

## 8. The decision log
`runs/<run>/decisions.jsonl` (CSV: `zirak agent export <run>`). One record per decision. A taken candidate (verbatim from a sample-data backtest early in the run, when the model was still on its
smoothed prior and no LLM was configured; with more data `source` becomes `gbm`/`logit`, with an LLM key the
posture's `source` becomes `llm:<model>`):
```json
{"id": "D000034", "ts": "2026-09-18T14:00:00+00:00", "kind": "candidate", "symbol": "ETHTMN", "setup": "breakout",
 "price": 578858528.0, "tp_pct": 2.5919, "sl_pct": 1.2959, "max_bars": 24,
 "indicators": {"rsi_14": 74.32, "bb_pctb": 1.08, "atr_pct": 0.864, "vol_z": 1.48, "...": "..."},
 "features": {"ret_1": 0.41, "...": "all 22 model inputs"},
 "signal_fa": "شکست سقف با حجم: قیمت بالای سقف ۴۸ کندل قبل بسته شد و حجم ۱٫۵ انحراف معیار بالاتر از معمول بود. ...",
 "model": {"id": "prior-210a1c8ec0", "source": "prior", "prob": 0.5294, "ev_pct": 0.2873, "kelly": 0.1357,
           "size_mult": 0.5429, "why": "p=0.53, EV=+0.29% >= 0.05%, kelly=0.14", "cost_pct": 0.475},
 "posture": {"stance": "normal", "mult": 1.0, "source": "rules", "reason_fa": "روند صعودی منظم است؛ همهٔ الگوها مجازند."},
 "risk": {"equity_tmn": "5000000", "risk_tmn": "16287", "bound_by": "risk_based", "value_tmn": "1256123", "qty": "0.00217"},
 "action": "buy", "reason_fa": "... مدل: احتمال ۵۳٪، ارزش مورد انتظار ۰٫۲۹٪؛ حجم ۱٬۲۵۶٬۱۲۳ تومان."}
```
Other kinds: `entry_filled`, `entry_unfilled`, `exit_order`, `exit` (with P&L), `guard` (status changes),
`model` (retraining, with the model card), `reconcile`, `kill`. Every order with its acknowledgement time
is in `orders.jsonl`; closed round trips in `trades.jsonl`; equity in `equity.csv`.

## 9. Backtest, shadow test and reproducibility
- **Backtest**: `zirak agent backtest --days 30` replays history through the same engine with walk-forward
  retraining, then writes `report.md` in the judges' metrics: realised and mark-to-market return, max
  drawdown, number of trades, volume, average trade volume, trades per day, exits, AI statistics
  (candidates / taken / skipped by the model / by the posture), latency and errors.
- **Shadow test**: `zirak agent shadow` runs on live Wallex data with paper fills on the real order book,
  same journal and report. Run it for at least a few hours before going live.
- **Verify**: `zirak agent verify <run>` recomputes every logged AI verdict from the logged features and the
  saved model snapshot, and checks that no buy contradicted the posture or happened while the guard was
  paused. On the bundled sample: 100 % of verdicts reproduced. Two backtests with the same data and config
  produce identical decisions (tested in `tests/test_agent.py`).

### Results so far (honest)
On the bundled **real** Wallex sample (60 days of 1-hour candles, 5 markets; `config/sample-1h.json`,
placeholder fees 0.25 % taker / 0.20 % maker), last 30 days, walk-forward: **+0.18 % mark-to-market,
−0.6 % realised, max drawdown 1.4 %, 12 trades** (mean reversion profitable, breakouts and the one
basis trade not). Gross of costs, mean reversion (+0.51 % per trade) and breakouts (+0.40 %) have an
edge on this data; at 0.25 % fees most of it is eaten, which is why the model's EV gate (with the account's
*real* fee tier) and maker-first execution matter more than any single indicator. The challenge config
(15-minute bars) must be trained and backtested on backfilled 1-minute history from a machine that can
reach Wallex (see the run book); its results will be added here.

## 10. Re-run it yourself
```bash
cd backend && pip install -e ".[dev]"
zirak agent backtest --config config/sample-1h.json --days 30      # bundled real sample, offline
zirak agent verify ../data/runs/<run>                              # recompute every AI decision
zirak agent export ../data/runs/<run>                              # decisions.csv
# with Wallex access (from Iran): history, training, the challenge config
zirak backfill --days-1m 45 && zirak agent train && zirak agent backtest --days 14
zirak agent shadow                                                 # live data, paper orders
```
Docker: `GIT_COMMIT=$(git rev-parse HEAD) docker compose --profile shadow up -d --build`.

## 11. Limits and open points (UNVERIFIED)
- Order status values, `openOrders` shape and the fee rate unit are confirmed only by the day-0 probe
  (`zirak agent probe`), see [wallex-api/README.md](wallex-api/README.md).
- Whether spot calls on the credit account need the `sub-account-client-id` header (the probe checks it).
- Spot minimum order sizes are placeholders (100,000 TMN).
- The LLM posture is only as good as the provider configured; without one the rule posture is used and the
  logs say so.
