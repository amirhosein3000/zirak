# Run book — the 3 challenge days

Everything below runs from `backend/` (venv active) on a machine that can reach `api.wallex.ir`
(a laptop or VPS **in Iran**; Wallex isn't reachable from abroad). Docker alternatives are in brackets.
Never turn live on before the risk limits are confirmed (step 5).

## 0. Before the start (T−1 day)
```bash
git pull && pip install -e ".[dev]"                 # [docker compose build]
cp ../.env.example ../.env                           # then edit ../.env:
#   WALLEX_API_KEY=<the CREDIT account's own key, trading permission only>
#   WALLEX_CREDIT_ACCOUNT=true
#   WALLEX_SUB_ACCOUNT_CLIENT_ID=<clientId of the credit account, if given>
#   WALLEX_PROP_PACKAGE_ID=<package id, if given>        (its unavailableMarkets are removed automatically)
#   LLM_BASE_URL / LLM_API_KEY / LLM_MODEL, MOCK_LLM=false  (the posture agent; optional but scores AI points)
#   LIVE_TRADING=false   (stays false until step 5)
#   MAX_ORDER_TMN=1500000  MAX_ORDER_USDT=50  DAILY_LOSS_LIMIT_PCT=2.5
```
Set the challenge window: `ZIRAK_CHALLENGE_START=...Z` / `ZIRAK_CHALLENGE_END=...Z` in `../.env` (or the GitHub
variables of the same name for Liara), or `config/challenge.json` → `"clock"` (UTC!
Tehran is UTC+3:30). The engine stops new entries 4 h before the end and is all Toman 30 min before it.

## 1. Data and model (≈ 10 min)
```bash
zirak backfill --days-1m 45 --days-1h 180            # history for BTC/ETH/USDT Toman + USDT pairs
zirak data-stats                                     # check 1m rows for every market
zirak agent train                                    # -> data/models/challenge/model_card.json
zirak agent backtest --days 14                       # walk-forward on the challenge config (15m)
zirak agent verify ../data/runs/<that run>           # must say "ok": true
```
Read `report.md` and `model_card.json` (holdout AUC, EV of taken trades). If the model takes trades with
negative holdout EV, raise `model.min_ev_pct` in the config and retrain — never lower the risk limits instead.

## 2. Day-0 probe on the real account (with the user watching)
Temporarily set `LIVE_TRADING=true` (all live conditions must hold), then:
```bash
zirak agent probe --symbol USDTTMN --yes
```
It prints balances (credit account), the plan's warning/liquidation limits, fees, then places ONE tiny
LIMIT buy 30 % below the market, reads it back, lists open orders, cancels it and reads it again.
Check and note in `docs/wallex-api/README.md`: order status names, `openOrders` shape, fee unit, whether
the sub-account header is needed. Set `LIVE_TRADING=false` again.

## 3. Shadow test (≥ 2–3 hours, ideally overnight)
```bash
zirak agent shadow                                   # [GIT_COMMIT=$(git rev-parse HEAD) docker compose --profile shadow up -d --build]
zirak agent report ../data/runs/challenge-shadow     # any time, from another terminal
```
Expect candidates and decisions in `decisions.jsonl` on every 15-minute bar, postures every hour
(`source: llm:<model>` if the LLM works), no errors.

## 4. Recorder (all 3 days, separate terminal)
```bash
zirak record                                         # [docker compose --profile recorder up -d]
```

## 5. Go live — only after the user confirms the limits
Confirm with the user: risk per trade 0.6 %, max position 30 %, max exposure 70 %, `MAX_ORDER_TMN`,
daily loss 2.5 %, drawdown pause 5 % / kill 8 %, liquidation cushion 60 % / 30 %, end-of-challenge flatten.
Then set `LIVE_TRADING=true` in `.env` and:
```bash
zirak agent live --i-understand-this-is-real-money   # [GIT_COMMIT=$(git rev-parse HEAD) docker compose --profile live up -d --build]
```
The run directory is `data/runs/challenge-live/`. Re-running the same command after a crash or reboot
**resumes** it (state + reconciliation with the account). Keep the shadow run going in parallel: shadow vs
live on the same data is extra evidence for the judges.

## 6. During the challenge
| Check | Command |
|---|---|
| Report (return, drawdown, trades, volume, latency, errors) | `zirak agent report ../data/runs/challenge-live` |
| Latest decisions | `tail -n 5 ../data/runs/challenge-live/decisions.jsonl` |
| Guard state / positions | `cat ../data/runs/challenge-live/state.json` |
| Official plan profit and limits (from Wallex, refreshed every 10 min) | `state.json` → `package` |

Do not place manual orders on the challenge account (disqualifying, and the agent would cancel unknown
orders at the next restart anyway).

## 7. Emergencies
- **Stop everything now**: `zirak kill` (cancels all open orders, stops the agent; positions stay).
  [`docker compose exec agent-live zirak kill`]
- **Sell everything to Toman**: `zirak agent flatten --yes` (after `zirak kill`).
- Resume after a kill: `zirak reset-kill`, then the live command again.
- Something broken in code: kill first, fix, run the quality gates, commit, **then** restart (the delivered
  code must equal the code that traded; every run manifest records its commit).

## 8. After the end (deliverables)
```bash
zirak agent report ../data/runs/challenge-live
zirak agent verify ../data/runs/challenge-live
zirak agent export ../data/runs/challenge-live       # decisions.csv
zirak agent report ../data/runs/challenge-shadow
```
Commit the run directories' `report.md`, `report.json`, `decisions.csv`, `decisions.jsonl`, `postures.jsonl`,
`trades.jsonl`, `orders.jsonl`, `equity.csv`, `manifest.json` and `models/` under `docs/challenge/results/`
(no secrets are in them), update the results section of `docs/ALGORITHM.md`, record the demo video
([demo-video.md](demo-video.md)), push, and tag the commit `challenge-final`.
