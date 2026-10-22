# Wallex challenge — analysis and plan

The official text is in [spec.md](spec.md). This file is our reading of it, how points map to the
system, and the plan. The engine's technical document for the judges is [../ALGORITHM.md](../ALGORITHM.md).

## The spec in 6 bullets
1. **Build an automated, AI-driven trading engine** that runs on a real Wallex challenge account
   (5,000,000 TMN of Wallex credit, «طرح معامله اعتباری»), for **3 days**, with no manual trades.
2. **Score 300 = 150 trading + 150 technical.** Trading: return rank 90 (*a losing team gets 0 here*),
   loss control 30 (intra-challenge drawdown), activity 15 (regular, sensible trading on all 3 days),
   stability 15 (few errors, correct orders, no crashes). Technical: strategy logic 40, **real AI in the
   decisions 35** ("not if/else with an AI label"), risk and capital management 30, re-runnable 25,
   backtest + shadow test 20.
3. **Return is measured in Toman, realised.** The organisers' note: at the end nothing may be held as a
   coin (USDT is a coin too); the score is the strategy's realised result, not price moves of held coins.
4. **Rules:** only markets allowed for the credit plan; no self-trading, coordinated or wash trading;
   the delivered code must be the code that traded; every trade needs a stored reason (decision log).
5. **Deliverables:** ~5-minute demo video (mandatory; quality counts; show outputs, not code), GitHub repo,
   one md document (architecture, AI use and Wallex tools, buy/sell conditions, risk and capital
   management, how to re-run and evaluate), and the decision logs.
6. **Tools:** Wallex API, Wallex MCP, any AI models or agent frameworks.

## What the points reward, and what we do about each
| Points | What earns them | Our design |
|---:|---|---|
| 90 | Positive realised return, ranked | Trade only when the model's expected value after fees is positive; small, many, independent bets; maker-first orders to cut fees; never hold coins at the end |
| 30 | Shallow intra-challenge drawdown | Risk per trade 0.6 % of equity at the stop, exposure caps, daily-loss and peak-drawdown circuit breakers, distance-to-liquidation guard |
| 15 | Regular, reasonable activity on all 3 days | Several markets × several setups on 15-minute bars; activity is reported per day; no forced or wash trades |
| 15 | Stability | Persistent state + restart reconciliation, idempotent orders (`client_id`), throttling, retries on reads only, stale-data guard, health file, process supervisor (Docker `restart: unless-stopped`) |
| 40 | Clear strategy logic | Every trade = explainable setup + model probability + agent posture + risk decision, stored as one decision record |
| 35 | Real AI in the decision | **ML meta-labeler** decides take/skip and size for *every* candidate (triple-barrier labels, walk-forward training). **LLM agent with tools** sets each market's risk posture hourly. Both are logged; neither can bypass the hard limits |
| 30 | Risk and capital management | Hard caps independent of the AI: per-order cap, max position, max exposure, stop-loss on every position, daily loss, drawdown, liquidation distance, end-of-challenge flatten, kill switch |
| 25 | Re-runnable | One config file, one command per mode, Docker, seeded model, cached LLM answers, `zirak agent verify` re-plays recorded inputs and checks the decisions match |
| 20 | Backtest + shadow | Same engine code in backtest (history), shadow (live data, paper fills on the real order book) and live; a report for each in the judges' metrics |

## Requirement map
| Requirement | Status before | Work |
|---|---|---|
| Market data from Wallex | Done (`exchange/wallex.py`) | add 15m features from 1m candles |
| Credit sub-account (own key, own wallet) | Not handled | read-only: `GET /v1/account/balances-detail`, `GET /v1/prop/user/packages/active` (warning / liquidation limits, official profit), `GET /v1/prop/packages/{id}` (`unavailableMarkets`). **No transfer / close calls, ever** |
| Multi-market on one account | Bot = one market | new portfolio agent (`zirak/agent/`) sharing one balance |
| AI deciding | LLM only explains | ML meta-labeler + LLM posture agent with tool calls |
| End flat in Toman | Not handled | challenge clock: no new entries late, staged flatten, final check that only TMN remains |
| Restart safety | In-memory ledger | SQLite state, reconcile with balances / open orders on start |
| Decision log per trade | Bot log (per signal) | one JSONL record per decision + CSV export, incl. model inputs/outputs and agent posture |
| Speed | Not measured | latency per order: decision → ack → fill, in the report |
| Backtest / shadow | Backtest + paper-live (single strategy) | agent backtest, agent shadow mode, judge-metric reports, replay verification |
| Wallex MCP | — | Agent tools are a plain Python tool layer; the same tools are served by a **Zirak MCP server**. The official Wallex MCP isn't in our docs yet: when the organisers publish it, it plugs into the agent's *read-only* tools. Orders always go through our guarded engine |

## Architecture (one code path for backtest, shadow and live)
```
 Wallex REST (candles 1m→15m, depth, trades, balances-detail, package limits)
        │
        ▼
 Feature engine ──► Setup scanners (explainable candidates: mean-reversion, trend pullback, breakout)
        │                      │
        │                      ▼
        │            ML meta-labeler: P(take-profit before stop | features), EV after fees, size
        │                      │
        ├──► LLM posture agent (tool calls, hourly): per market stance + risk multiplier (bounded, cached)
        │                      │
        ▼                      ▼
 Account guard (drawdown, daily loss, liquidation distance, challenge clock) ─► Risk sizing (hard caps)
        │
        ▼
 Execution (maker-first limit → marketable fallback; bracket exits: resting take-profit, active stop,
            time stop; TTL; idempotent client ids; throttle)  ─►  WallexClient (live) | PaperExchange (shadow/backtest)
        │
        ▼
 State store (SQLite) + decision log (JSONL/CSV) + metrics (trades, volume, latency, drawdown)
```

## Risk limits (proposed; **the user must confirm before live**)
| Limit | Proposal | Why |
|---|---|---|
| Risk per trade | 0.6 % of equity at the stop (≈ 30,000 TMN) | ~16 consecutive losers before −10 % |
| Max position (one market) | 30 % of equity | never "all in" |
| Max total exposure | 70 % of equity | cash buffer for fees, slippage, new chances |
| Hard per-order cap `MAX_ORDER_TMN` | 1,500,000 TMN | env cap, checked again in the Executor |
| Daily loss limit | 2.5 % → no new entries until the next UTC day | 30 drawdown points |
| Peak drawdown | 5 % → entries paused (exits continue); 8 % → flatten and kill switch | |
| Liquidation guard | stop entries if equity < liquidation limit × 1.3 | credit plans auto-close at the liquidation limit |
| Challenge end | no entries in the last 4 h; flatten from T−90 min; marketable flatten at T−30 min | realised Toman at the end |

## What needs the user
1. The challenge **API key** of the credit account (trade permission only) and its **start/end time**.
2. An **LLM key** (OpenAI-compatible; any provider). Without it the agent uses its deterministic
   fallback posture and the docs say so; the ML meta-labeler works without any key.
3. **Data**: run `zirak backfill --days-1m 45` from a machine in Iran (Wallex isn't reachable from abroad),
   then `zirak agent train`.
4. A **supervised day-0 check** on the real account: `zirak agent probe` (one tiny order far from the
   market, read back, cancel) to confirm the order fields still marked UNVERIFIED.
5. **Confirm the risk limits** above. LIVE_TRADING stays false until then.
