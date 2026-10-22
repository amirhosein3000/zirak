# Strategy research (walk-forward, out-of-sample only)

_Run: 2026-10-22 with `zirak research` (raw numbers: [research-results.json](research-results.json))._

## The honest conclusion

**Nothing survived.** 0 of 75 configurations (5 strategies × 5 markets × 3 resolutions) passed all three
bars out of sample. The main reasons:

1. **Too little data for the trade-count bar.** The committed real Wallex sample has only 60 days of 1h
   candles (aggregated to 4h) and 400 days of 1d. With 3 test windows per run, no strategy reached 30
   closed trades except the hourly grid, and the grid lost money after fees every time.
2. **Fees dominate small edges.** With the placeholder taker fee of 0.25 % (UNVERIFIED; real tiers may be
   lower) one round trip costs ~0.6 % with slippage. Most entries that were positive in sample were
   flat or negative out of sample.
3. **The period was a strong rally in Toman terms.** Buy-and-hold made +8 % to +35 % on most markets
   (USDTTMN alone rose ~26 % over 400 days: the Toman lost value). Any strategy that sits in cash most
   of the time can't keep up with that on return; it can only win on drawdown.

What *did* hold up, and is worth re-testing on more data:

- **Every strategy cut drawdown hard.** Out of sample, the worst strategy drawdown was 8 % against
  buy-and-hold drawdowns of 5–39 %. The risk layer works; the entries are the weak part.
- **The dip-buy rule** (the product's example sentence: buy 10 % when price is 3 % below its 24-hour high,
  take profit at +5 %, stop at −5 %) chose **the same parameters in every window** (a sign of stability
  rather than curve fitting), was positive out of sample on 4 of 5 hourly markets
  (BTCTMN +1.0 %, ETHTMN +1.1 %, USDTTMN +0.6 %, BTCUSDT +0.2 %, ETHUSDT −0.6 %) with drawdowns under
  1.3 %. But that's 19 trades in total: **not proof of anything**.
- **Holding cash in Toman is not "doing nothing".** In Toman markets idle Toman loses to USDT over time.
  For a Toman-scored contest, a USDT reserve is a real (directional) alternative to compare against.

## Method

- Data: real Wallex candles from `backend/tests/fixtures/wallex` (Wallex was not reachable from the
  research machine for a fresh backfill). 4h is aggregated from 1h locally.
- Walk-forward: train window → choose parameters → trade them on the next unseen test window → roll
  forward by one test window. Windows: 1h train 480 / test 240 candles (20 / 10 days); 4h 120 / 60;
  1d 120 / 60. 100 earlier candles are given as indicator history but never traded.
- Parameter choice on the train window: maximise `return + 0.5 × max drawdown` (drawdown is negative),
  needing at least 2 trades. Grids are deliberately small (6–9 combinations each).
- Every run uses the normal backtester (same Bot, RiskManager and PaperExchange as paper/live) with
  taker 0.25 %, maker 0.20 % (both UNVERIFIED placeholders), 5 bps slippage, volume participation cap,
  orders filled on the next candle, risk defaults: stop-loss 5 %, daily loss limit 5 %, max position 80 %.
- Out-of-sample windows are compounded into one equity curve; buy-and-hold is compounded over the same
  windows and pays the same fees.
- A configuration survives only if out of sample it (1) closed ≥ 30 trades, (2) made money (beat
  holding cash), and (3) had a smaller max drawdown than buy-and-hold. "Trades" = closed round trips, so
  a position still open at the end counts 0 (that's why a few rows show a return with 0 trades).

## Results

### 1h

| Market | Strategy | OOS return | OOS max DD | OOS trades | B&H return | B&H max DD | Verdict |
|---|---|---:|---:|---:|---:|---:|---|
| USDTTMN | EMA cross | -1.59 % | -2.44 % | 4 | +14.65 % | -6.54 % | too few trades; lost money |
| USDTTMN | RSI reversion | +0.40 % | -2.35 % | 3 | +14.65 % | -6.54 % | too few trades |
| USDTTMN | Grid | -1.99 % | -2.70 % | 47 | +14.65 % | -6.54 % | lost money |
| USDTTMN | DCA | +0.39 % | -3.19 % | 4 | +14.65 % | -6.54 % | too few trades |
| USDTTMN | Dip-buy rule | +0.57 % | -0.20 % | 3 | +14.65 % | -6.54 % | too few trades |
| BTCTMN | EMA cross | +0.97 % | -4.95 % | 5 | +23.51 % | -9.86 % | too few trades |
| BTCTMN | RSI reversion | -0.02 % | -1.41 % | 2 | +23.51 % | -9.86 % | too few trades; lost money |
| BTCTMN | Grid | -1.85 % | -1.86 % | 24 | +23.51 % | -9.86 % | too few trades; lost money |
| BTCTMN | DCA | -0.14 % | -3.12 % | 7 | +23.51 % | -9.86 % | too few trades; lost money |
| BTCTMN | Dip-buy rule | +1.01 % | -0.56 % | 2 | +23.51 % | -9.86 % | too few trades |
| BTCUSDT | EMA cross | -3.55 % | -3.74 % | 6 | +8.20 % | -7.78 % | too few trades; lost money |
| BTCUSDT | RSI reversion | +0.48 % | -1.83 % | 3 | +8.20 % | -7.78 % | too few trades |
| BTCUSDT | Grid | -1.70 % | -1.70 % | 21 | +8.20 % | -7.78 % | too few trades; lost money |
| BTCUSDT | DCA | +0.54 % | -2.22 % | 3 | +8.20 % | -7.78 % | too few trades |
| BTCUSDT | Dip-buy rule | +0.20 % | -0.46 % | 2 | +8.20 % | -7.78 % | too few trades |
| ETHTMN | EMA cross | -0.76 % | -6.66 % | 4 | +17.66 % | -15.05 % | too few trades; lost money |
| ETHTMN | RSI reversion | +0.07 % | -3.31 % | 4 | +17.66 % | -15.05 % | too few trades |
| ETHTMN | Grid | -2.98 % | -3.00 % | 14 | +17.66 % | -15.05 % | too few trades; lost money |
| ETHTMN | DCA | +0.48 % | -4.13 % | 4 | +17.66 % | -15.05 % | too few trades |
| ETHTMN | Dip-buy rule | +1.10 % | -0.95 % | 6 | +17.66 % | -15.05 % | too few trades |
| ETHUSDT | EMA cross | +1.32 % | -4.29 % | 20 | +2.27 % | -15.82 % | too few trades |
| ETHUSDT | RSI reversion | -3.74 % | -5.84 % | 6 | +2.27 % | -15.82 % | too few trades; lost money |
| ETHUSDT | Grid | -2.02 % | -2.19 % | 20 | +2.27 % | -15.82 % | too few trades; lost money |
| ETHUSDT | DCA | -3.52 % | -5.21 % | 4 | +2.27 % | -15.82 % | too few trades; lost money |
| ETHUSDT | Dip-buy rule | -0.56 % | -1.29 % | 6 | +2.27 % | -15.82 % | too few trades; lost money |

### 4h

| Market | Strategy | OOS return | OOS max DD | OOS trades | B&H return | B&H max DD | Verdict |
|---|---|---:|---:|---:|---:|---:|---|
| USDTTMN | EMA cross | -1.15 % | -1.40 % | 1 | +3.81 % | -5.41 % | too few trades; lost money |
| USDTTMN | RSI reversion | +0.99 % | -0.30 % | 1 | +3.81 % | -5.41 % | too few trades |
| USDTTMN | Grid | -0.30 % | -1.48 % | 12 | +3.81 % | -5.41 % | too few trades; lost money |
| USDTTMN | DCA | +0.09 % | -0.43 % | 1 | +3.81 % | -5.41 % | too few trades |
| USDTTMN | Dip-buy rule | +0.22 % | -0.08 % | 1 | +3.81 % | -5.41 % | too few trades |
| BTCTMN | EMA cross | -1.51 % | -1.51 % | 1 | +1.96 % | -10.34 % | too few trades; lost money |
| BTCTMN | RSI reversion | +0.00 % | 0.00 % | 0 | +1.96 % | -10.34 % | too few trades; lost money |
| BTCTMN | Grid | -0.97 % | -1.21 % | 12 | +1.96 % | -10.34 % | too few trades; lost money |
| BTCTMN | DCA | -0.64 % | -1.47 % | 3 | +1.96 % | -10.34 % | too few trades; lost money |
| BTCTMN | Dip-buy rule | +0.40 % | -0.89 % | 2 | +1.96 % | -10.34 % | too few trades |
| BTCUSDT | EMA cross | -2.23 % | -3.44 % | 3 | -2.51 % | -7.51 % | too few trades; lost money |
| BTCUSDT | RSI reversion | -1.15 % | -1.34 % | 0 | -2.51 % | -7.51 % | too few trades; lost money |
| BTCUSDT | Grid | -0.94 % | -2.45 % | 14 | -2.51 % | -7.51 % | too few trades; lost money |
| BTCUSDT | DCA | -0.50 % | -1.24 % | 1 | -2.51 % | -7.51 % | too few trades; lost money |
| BTCUSDT | Dip-buy rule | -0.26 % | -0.61 % | 1 | -2.51 % | -7.51 % | too few trades; lost money |
| ETHTMN | EMA cross | +0.00 % | 0.00 % | 0 | -7.01 % | -17.91 % | too few trades; lost money |
| ETHTMN | RSI reversion | +0.48 % | 0.00 % | 0 | -7.01 % | -17.91 % | too few trades |
| ETHTMN | Grid | -1.62 % | -2.36 % | 16 | -7.01 % | -17.91 % | too few trades; lost money |
| ETHTMN | DCA | -1.10 % | -1.25 % | 4 | -7.01 % | -17.91 % | too few trades; lost money |
| ETHTMN | Dip-buy rule | -1.41 % | -2.42 % | 4 | -7.01 % | -17.91 % | too few trades; lost money |
| ETHUSDT | EMA cross | -3.53 % | -3.53 % | 4 | -9.93 % | -15.15 % | too few trades; lost money |
| ETHUSDT | RSI reversion | -2.10 % | -2.21 % | 1 | -9.93 % | -15.15 % | too few trades; lost money |
| ETHUSDT | Grid | -4.83 % | -4.95 % | 20 | -9.93 % | -15.15 % | too few trades; lost money |
| ETHUSDT | DCA | -1.80 % | -2.16 % | 2 | -9.93 % | -15.15 % | too few trades; lost money |
| ETHUSDT | Dip-buy rule | -0.33 % | -0.79 % | 2 | -9.93 % | -15.15 % | too few trades; lost money |

### 1d

| Market | Strategy | OOS return | OOS max DD | OOS trades | B&H return | B&H max DD | Verdict |
|---|---|---:|---:|---:|---:|---:|---|
| USDTTMN | EMA cross | +4.60 % | -8.02 % | 3 | +25.60 % | -18.90 % | too few trades |
| USDTTMN | RSI reversion | +1.49 % | -1.61 % | 0 | +25.60 % | -18.90 % | too few trades |
| USDTTMN | Grid | +0.69 % | -0.55 % | 4 | +25.60 % | -18.90 % | too few trades |
| USDTTMN | DCA | +0.05 % | -0.77 % | 4 | +25.60 % | -18.90 % | too few trades |
| USDTTMN | Dip-buy rule | -0.28 % | -1.32 % | 6 | +25.60 % | -18.90 % | too few trades; lost money |
| BTCTMN | EMA cross | +11.04 % | -3.93 % | 1 | +27.21 % | -33.62 % | too few trades |
| BTCTMN | RSI reversion | -3.25 % | -3.75 % | 1 | +27.21 % | -33.62 % | too few trades; lost money |
| BTCTMN | Grid | -1.75 % | -2.75 % | 5 | +27.21 % | -33.62 % | too few trades; lost money |
| BTCTMN | DCA | +0.80 % | -0.98 % | 6 | +27.21 % | -33.62 % | too few trades |
| BTCTMN | Dip-buy rule | -2.08 % | -3.08 % | 6 | +27.21 % | -33.62 % | too few trades; lost money |
| BTCUSDT | EMA cross | +2.81 % | -3.83 % | 2 | +1.20 % | -26.88 % | too few trades |
| BTCUSDT | RSI reversion | -6.32 % | -6.32 % | 2 | +1.20 % | -26.88 % | too few trades; lost money |
| BTCUSDT | Grid | -1.71 % | -2.63 % | 9 | +1.20 % | -26.88 % | too few trades; lost money |
| BTCUSDT | DCA | +0.07 % | -0.98 % | 3 | +1.20 % | -26.88 % | too few trades |
| BTCUSDT | Dip-buy rule | -1.19 % | -2.73 % | 7 | +1.20 % | -26.88 % | too few trades; lost money |
| ETHTMN | EMA cross | +27.16 % | -3.53 % | 0 | +34.86 % | -39.12 % | too few trades |
| ETHTMN | RSI reversion | -1.10 % | -6.46 % | 2 | +34.86 % | -39.12 % | too few trades; lost money |
| ETHTMN | Grid | -6.44 % | -7.05 % | 5 | +34.86 % | -39.12 % | too few trades; lost money |
| ETHTMN | DCA | +3.31 % | -0.82 % | 6 | +34.86 % | -39.12 % | too few trades |
| ETHTMN | Dip-buy rule | -2.05 % | -4.97 % | 11 | +34.86 % | -39.12 % | too few trades; lost money |
| ETHUSDT | EMA cross | +18.64 % | -2.82 % | 0 | +7.01 % | -33.78 % | too few trades |
| ETHUSDT | RSI reversion | -1.62 % | -4.17 % | 1 | +7.01 % | -33.78 % | too few trades; lost money |
| ETHUSDT | Grid | -0.97 % | -1.35 % | 8 | +7.01 % | -33.78 % | too few trades; lost money |
| ETHUSDT | DCA | +1.56 % | -0.65 % | 3 | +7.01 % | -33.78 % | too few trades |
| ETHUSDT | Dip-buy rule | +0.42 % | -3.43 % | 14 | +7.01 % | -33.78 % | too few trades |

## Presets

No configuration earned the "validated" label, so there are **no validated presets**. The candidates
below are kept in `backend/zirak/strategy/presets.py` with `validated=False`, and the UI/docs must
present them as experiments, not recommendations.

| Preset | Rule | Persian one-liner |
|---|---|---|
| `dip3_tp5` | buy 10 % of equity when price is 3 % under its 24h high; TP +5 %, SL −5 % (1h) | خرید پله‌ای کوچک در افت‌های ۳٪ با حد سود ۵٪ و حد ضرر ۵٪ |
| `rsi_calm` | RSI(14) < 30 buy 40 %, sell at RSI > 65; SL −5 % (1h) | خرید در اشباع فروش و فروش در برگشت، با حد ضرر ۵٪ |

## Default for competition mode (and why)

`zirak compete` without a config now runs the **dip-buy rule on BTCTMN and ETHTMN (1h), 25 % of the
Toman balance each, with 10 % position steps**, a −5 % stop per trade, a 2 % per-entry daily loss limit,
and team limits of 8 % max drawdown and 3 % daily loss (the kill switch fires on breach). Half of the
capital stays in reserve.

Why: it had the smallest out-of-sample drawdowns of anything tested, it picked the same parameters in
every window, and it trades rarely, so fees can't bleed it. It is chosen for **survival**, not for
return: in a rally it will lag buy-and-hold badly, and the evidence for its edge is thin (19 trades).
If the contest is scored only on PnL in Toman during a Toman devaluation, discuss a USDT reserve
sleeve before the event; it's a directional bet, so it isn't the default.

## Next research steps

1. Run `zirak backfill` (180 days of 1h) and `zirak record` from a machine in Iran, then re-run
   `zirak research`. With 180 days the 1h runs get ~13 test windows and a real chance at 30 trades.
2. Read the real fee tier with an API key (`GET /v1/account/fee`) and re-run: fees decide most rows.
3. Add the regime gate (`modules/regime.py`) as a research dimension once there is enough data.
