# Demo video (≈ 5 minutes) — script

The spec: ~5 minutes, show **outputs** (not code), explain the work fully; quality counts. Record the
screen at 1080p with voice (Persian). Have ready: a terminal with large font, the `/agent` page of the web
app, the live run directory, `report.md` of the live, shadow and backtest runs.

| Time | Show | Say (Persian, roughly) |
|---|---|---|
| 0:00–0:30 | Title slide / the `/agent` page | «زیرک یک عامل معاملاتی خودکار برای بازارهای تومانی والکس است: تحلیل می‌کند، با هوش مصنوعی تصمیم می‌گیرد، با محدودیت‌های سخت ریسک اجرا می‌کند و دلیل هر تصمیم را ثبت می‌کند.» |
| 0:30–1:15 | The architecture diagram (docs/ALGORITHM.md §2) | Data → explainable setups → **ML meta-labeler** (probability of take-profit before stop, EV after real fees, Kelly size) → **LLM agent with tools** (hourly posture per market) → hard risk layer → maker-first execution. «هوش مصنوعی واقعاً تصمیم می‌گیرد، ولی هیچ‌وقت از سقف‌های ریسک عبور نمی‌کند.» |
| 1:15–2:15 | `/agent` page of the **live** run: equity curve, open positions, decision feed; click a decision | Walk through one real trade: the signal (e.g. mean reversion, RSI 28), the model's probability and EV, the posture (and the LLM's reason), the size and which cap bound it, the take-profit/stop, the exit and P&L. Then one **skipped** candidate: «مدل رد کرد چون ارزش مورد انتظار بعد از کارمزد منفی بود.» |
| 2:15–2:50 | `postures.jsonl` / the posture card | The agent's tool calls (market snapshot, portfolio, model stats) and its decision: e.g. ETH cautious ×0.5 after a volatility spike. |
| 2:50–3:30 | `report.md` of the live run | Judges' metrics: realised return in Toman, max drawdown, number of trades, volume, average trade size, trades per day (all 3 days), order latency, errors = 0, open positions at the end = 0 (all Toman). |
| 3:30–4:10 | Backtest + shadow reports side by side; terminal: `zirak agent verify ...` → `"reproduced_pct": 100.0` | «همان کد در بک‌تست، تست سایه و معاملهٔ واقعی اجرا شده. هر تصمیم هوش مصنوعی از روی لاگ‌ها دوباره محاسبه و تأیید می‌شود.» |
| 4:10–4:40 | Risk: the guard table (ALGORITHM.md §5); terminal: `zirak kill` on the shadow run | Per-trade risk 0.6 %, max position 30 %, max exposure 70 %, daily loss, drawdown and liquidation-cushion stops, end-of-challenge flatten; kill switch in one command. |
| 4:40–5:00 | GitHub repo, `docs/ALGORITHM.md`, run book | «کد، مستندات، لاگ تصمیم‌ها و راهنمای اجرای مجدد در گیت‌هاب است؛ داور با یک دستور می‌تواند بک‌تست را دوباره اجرا کند.» |

Fallback if the live run is short or flat: show the shadow run and the backtest, and say so plainly.
Never cut or edit numbers; the judges can recompute everything from the committed run directories.
